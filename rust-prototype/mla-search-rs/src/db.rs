use std::sync::Arc;

use anyhow::Result;
use arrow_array::types::Float32Type;
use arrow_array::{FixedSizeListArray, Int32Array, RecordBatch, RecordBatchIterator, StringArray};
use arrow_schema::{DataType, Field, Schema};

pub const EMBED_DIM: i32 = 384;
pub const TABLE: &str = "chunks";

pub fn schema() -> Arc<Schema> {
    Arc::new(Schema::new(vec![
        Field::new("id", DataType::Utf8, false),
        Field::new("file_path", DataType::Utf8, false),
        Field::new("content", DataType::Utf8, false),
        Field::new("start_line", DataType::Int32, false),
        Field::new("end_line", DataType::Int32, false),
        Field::new("file_hash", DataType::Utf8, false),
        Field::new(
            "embedding",
            DataType::FixedSizeList(
                Arc::new(Field::new("item", DataType::Float32, true)),
                EMBED_DIM,
            ),
            false,
        ),
    ]))
}

pub async fn open(path: &str) -> Result<lancedb::Connection> {
    Ok(lancedb::connect(path).execute().await?)
}

pub async fn open_or_create_table(
    db: &lancedb::Connection,
    schema: Arc<Schema>,
) -> Result<lancedb::Table> {
    let names = db.table_names().execute().await?;
    if names.iter().any(|n| n == TABLE) {
        return Ok(db.open_table(TABLE).execute().await?);
    }
    // Boş RecordBatch ilə cədvəl yarat
    let empty = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(Vec::<&str>::new())),
            Arc::new(StringArray::from(Vec::<&str>::new())),
            Arc::new(StringArray::from(Vec::<&str>::new())),
            Arc::new(Int32Array::from(Vec::<i32>::new())),
            Arc::new(Int32Array::from(Vec::<i32>::new())),
            Arc::new(StringArray::from(Vec::<&str>::new())),
            Arc::new(FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
                std::iter::empty::<Option<Vec<Option<f32>>>>(),
                EMBED_DIM,
            )),
        ],
    )?;
    let batches = RecordBatchIterator::new(vec![Ok(empty)].into_iter(), schema.clone());
    Ok(db.create_table(TABLE, Box::new(batches)).execute().await?)
}

pub struct ChunkRow<'a> {
    pub id: String,
    pub file_path: &'a str,
    pub content: &'a str,
    pub start_line: i32,
    pub end_line: i32,
    pub file_hash: &'a str,
    pub embedding: Vec<f32>,
}

pub fn rows_to_batch(rows: &[ChunkRow<'_>], schema: Arc<Schema>) -> Result<RecordBatch> {
    let ids: Vec<&str> = rows.iter().map(|r| r.id.as_str()).collect();
    let paths: Vec<&str> = rows.iter().map(|r| r.file_path).collect();
    let contents: Vec<&str> = rows.iter().map(|r| r.content).collect();
    let starts: Vec<i32> = rows.iter().map(|r| r.start_line).collect();
    let ends: Vec<i32> = rows.iter().map(|r| r.end_line).collect();
    let hashes: Vec<&str> = rows.iter().map(|r| r.file_hash).collect();

    let emb_array = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        rows.iter().map(|r| {
            Some(r.embedding.iter().map(|v| Some(*v)).collect::<Vec<_>>())
        }),
        EMBED_DIM,
    );

    Ok(RecordBatch::try_new(
        schema,
        vec![
            Arc::new(StringArray::from(ids)),
            Arc::new(StringArray::from(paths)),
            Arc::new(StringArray::from(contents)),
            Arc::new(Int32Array::from(starts)),
            Arc::new(Int32Array::from(ends)),
            Arc::new(StringArray::from(hashes)),
            Arc::new(emb_array),
        ],
    )?)
}
