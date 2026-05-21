use std::path::Path;
use std::sync::Arc;

use anyhow::{Context, Result};
use arrow_array::{Float32Array, Int32Array, RecordBatch, RecordBatchIterator, StringArray};
use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase};
use sha2::{Digest, Sha256};
use tokio::sync::Mutex;

use crate::chunker;
use crate::db;
use crate::walker;

// E5 ailəsi (multilingual-e5-large) hər iki tərəfdə prefix tələb edir:
//  - search query → "query: ..."
//  - indexed passage → "passage: ..."
// Eyni prefiks olmasa retrieval keyfiyyəti ciddi düşür.
const QUERY_PREFIX: &str = "query: ";
const PASSAGE_PREFIX: &str = "passage: ";

/// Reusable handle — embedding modeli və DB bağlantısını cache-də saxlayır.
/// MCP server-də bir dəfə yaradılır, hər tool call üçün təkrar istifadə olunur.
pub struct Server {
    model: Mutex<TextEmbedding>,
    db: lancedb::Connection,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct IndexResult {
    pub files_indexed: usize,
    pub chunks_total: usize,
    pub elapsed_seconds: f64,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct SearchHit {
    pub file_path: String,
    pub content: String,
    pub start_line: i32,
    pub end_line: i32,
    pub distance: f32,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Stats {
    pub table: String,
    pub chunks: usize,
}

impl Server {
    pub async fn new(db_path: impl Into<String>) -> Result<Self> {
        let db_path = db_path.into();
        let model = TextEmbedding::try_new(
            InitOptions::new(EmbeddingModel::MultilingualE5Large).with_show_download_progress(false),
        )
        .context("embedding model init")?;
        let db = db::open(&db_path).await?;
        Ok(Self {
            model: Mutex::new(model),
            db,
        })
    }

    pub async fn index_directory(&self, root: impl AsRef<Path>, reset: bool) -> Result<IndexResult> {
        let root = root.as_ref();
        let start = std::time::Instant::now();
        let files = walker::walk(root);
        let schema = db::schema();

        if reset && self.db.table_names().execute().await?.iter().any(|n| n == db::TABLE) {
            self.db.drop_table(db::TABLE).await?;
        }
        let table = db::open_or_create_table(&self.db, schema.clone()).await?;

        let mut total_chunks = 0usize;
        let mut indexed_files = 0usize;

        for ff in &files {
            let text = match std::fs::read_to_string(&ff.path) {
                Ok(t) => t,
                Err(_) => continue,
            };
            let chunks = chunker::chunk_text(&text);
            if chunks.is_empty() {
                continue;
            }
            let file_hash = hex::encode(Sha256::digest(text.as_bytes()));
            let rel_path = ff
                .path
                .strip_prefix(root)
                .unwrap_or(&ff.path)
                .to_string_lossy()
                .to_string();

            let contents: Vec<String> = chunks
                .iter()
                .map(|c| format!("{PASSAGE_PREFIX}{}", c.content))
                .collect();
            let embeddings = {
                let m = self.model.lock().await;
                m.embed(contents, None)?
            };

            let ids: Vec<String> = (0..chunks.len())
                .map(|_| uuid::Uuid::new_v4().to_string())
                .collect();

            let rows: Vec<db::ChunkRow> = chunks
                .iter()
                .zip(embeddings.into_iter())
                .zip(ids.iter())
                .map(|((chunk, emb), id)| db::ChunkRow {
                    id: id.clone(),
                    file_path: &rel_path,
                    content: &chunk.content,
                    start_line: chunk.start_line,
                    end_line: chunk.end_line,
                    file_hash: &file_hash,
                    embedding: emb,
                })
                .collect();

            let batch = db::rows_to_batch(&rows, schema.clone())?;
            let batches = RecordBatchIterator::new(vec![Ok(batch)].into_iter(), schema.clone());
            table.add(Box::new(batches)).execute().await?;

            total_chunks += chunks.len();
            indexed_files += 1;
        }

        Ok(IndexResult {
            files_indexed: indexed_files,
            chunks_total: total_chunks,
            elapsed_seconds: start.elapsed().as_secs_f64(),
        })
    }

    pub async fn search(&self, query: &str, top_k: usize) -> Result<Vec<SearchHit>> {
        let prefixed = format!("{QUERY_PREFIX}{query}");
        let q_emb: Vec<f32> = {
            let m = self.model.lock().await;
            let mut out = m.embed(vec![prefixed], None)?;
            out.remove(0)
        };
        let table = self.db.open_table(db::TABLE).execute().await?;
        let batches = table
            .vector_search(q_emb)?
            .limit(top_k)
            .execute()
            .await?
            .try_collect::<Vec<RecordBatch>>()
            .await?;

        let mut hits = Vec::new();
        for batch in &batches {
            let paths = batch
                .column_by_name("file_path")
                .and_then(|c| c.as_any().downcast_ref::<StringArray>());
            let contents = batch
                .column_by_name("content")
                .and_then(|c| c.as_any().downcast_ref::<StringArray>());
            let starts = batch
                .column_by_name("start_line")
                .and_then(|c| c.as_any().downcast_ref::<Int32Array>());
            let ends = batch
                .column_by_name("end_line")
                .and_then(|c| c.as_any().downcast_ref::<Int32Array>());
            let dists = batch
                .column_by_name("_distance")
                .and_then(|c| c.as_any().downcast_ref::<Float32Array>());

            for i in 0..batch.num_rows() {
                hits.push(SearchHit {
                    file_path: paths.map(|a| a.value(i)).unwrap_or("?").to_string(),
                    content: contents.map(|a| a.value(i)).unwrap_or("?").to_string(),
                    start_line: starts.map(|a| a.value(i)).unwrap_or(0),
                    end_line: ends.map(|a| a.value(i)).unwrap_or(0),
                    distance: dists.map(|a| a.value(i)).unwrap_or(f32::NAN),
                });
            }
        }
        Ok(hits)
    }

    pub async fn stats(&self) -> Result<Stats> {
        let names = self.db.table_names().execute().await?;
        if !names.iter().any(|n| n == db::TABLE) {
            return Ok(Stats {
                table: db::TABLE.to_string(),
                chunks: 0,
            });
        }
        let table = self.db.open_table(db::TABLE).execute().await?;
        let count = table.count_rows(None).await?;
        Ok(Stats {
            table: db::TABLE.to_string(),
            chunks: count,
        })
    }
}

pub fn shared(server: Server) -> Arc<Server> {
    Arc::new(server)
}
