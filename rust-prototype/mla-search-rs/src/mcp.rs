use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

use crate::server::Server;

const PROTOCOL_VERSION: &str = "2024-11-05";
const SERVER_NAME: &str = "mla-search-rs";
const SERVER_VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Deserialize)]
struct JsonRpcRequest {
    jsonrpc: String,
    id: Option<Value>,
    method: String,
    #[serde(default)]
    params: Value,
}

#[derive(Serialize)]
#[serde(untagged)]
enum JsonRpcResponse {
    Ok {
        jsonrpc: &'static str,
        id: Value,
        result: Value,
    },
    Err {
        jsonrpc: &'static str,
        id: Value,
        error: JsonRpcError,
    },
}

#[derive(Serialize)]
struct JsonRpcError {
    code: i32,
    message: String,
}

/// Stdio JSON-RPC server. Hər sətrdə bir JSON mesajı oxuyur, hər cavab yeni sətrdə yazılır.
/// Notification-lar (id-siz mesajlar) cavabsız qalır.
pub async fn serve(server: Arc<Server>) -> Result<()> {
    let stdin = tokio::io::stdin();
    let mut stdout = tokio::io::stdout();
    let mut reader = BufReader::new(stdin).lines();

    while let Some(line) = reader.next_line().await? {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let req: JsonRpcRequest = match serde_json::from_str(trimmed) {
            Ok(r) => r,
            Err(e) => {
                // Parse xətasında null id ilə xəta qaytar (JSON-RPC spec)
                write_response(
                    &mut stdout,
                    &JsonRpcResponse::Err {
                        jsonrpc: "2.0",
                        id: Value::Null,
                        error: JsonRpcError {
                            code: -32700,
                            message: format!("Parse error: {e}"),
                        },
                    },
                )
                .await?;
                continue;
            }
        };

        if req.jsonrpc != "2.0" {
            continue;
        }

        let is_notification = req.id.is_none();
        let id = req.id.clone().unwrap_or(Value::Null);

        let result = handle_method(&server, &req.method, req.params).await;

        // Notification-lara cavab qaytarılmır.
        if is_notification {
            continue;
        }

        let response = match result {
            Ok(value) => JsonRpcResponse::Ok {
                jsonrpc: "2.0",
                id,
                result: value,
            },
            Err(MethodError::NotFound) => JsonRpcResponse::Err {
                jsonrpc: "2.0",
                id,
                error: JsonRpcError {
                    code: -32601,
                    message: format!("Method not found: {}", req.method),
                },
            },
            Err(MethodError::InvalidParams(msg)) => JsonRpcResponse::Err {
                jsonrpc: "2.0",
                id,
                error: JsonRpcError {
                    code: -32602,
                    message: msg,
                },
            },
            Err(MethodError::Internal(msg)) => JsonRpcResponse::Err {
                jsonrpc: "2.0",
                id,
                error: JsonRpcError {
                    code: -32603,
                    message: msg,
                },
            },
        };
        write_response(&mut stdout, &response).await?;
    }

    Ok(())
}

async fn write_response(
    stdout: &mut tokio::io::Stdout,
    response: &JsonRpcResponse,
) -> Result<()> {
    let line = serde_json::to_string(response)?;
    stdout.write_all(line.as_bytes()).await?;
    stdout.write_all(b"\n").await?;
    stdout.flush().await?;
    Ok(())
}

enum MethodError {
    NotFound,
    InvalidParams(String),
    Internal(String),
}

async fn handle_method(
    server: &Arc<Server>,
    method: &str,
    params: Value,
) -> Result<Value, MethodError> {
    match method {
        "initialize" => Ok(json!({
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
            "capabilities": {
                "tools": {}
            }
        })),
        "initialized" | "notifications/initialized" => Ok(Value::Null),
        "ping" => Ok(json!({})),
        "tools/list" => Ok(json!({
            "tools": tools_descriptor()
        })),
        "tools/call" => handle_tools_call(server, params).await,
        _ => Err(MethodError::NotFound),
    }
}

fn tools_descriptor() -> Value {
    json!([
        {
            "name": "search_code",
            "description": "Vector-based semantic search over the indexed codebase. Returns top-K chunks ranked by cosine distance.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in natural language"},
                    "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50}
                },
                "required": ["query"]
            }
        },
        {
            "name": "index_directory",
            "description": "Walk a directory respecting .gitignore, chunk supported files, and store embeddings in LanceDB.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative directory path"},
                    "reset": {"type": "boolean", "default": false, "description": "Drop existing table before indexing"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "get_stats",
            "description": "Return the current chunk count and table name.",
            "inputSchema": {"type": "object", "properties": {}}
        }
    ])
}

async fn handle_tools_call(server: &Arc<Server>, params: Value) -> Result<Value, MethodError> {
    let name = params
        .get("name")
        .and_then(|v| v.as_str())
        .ok_or_else(|| MethodError::InvalidParams("missing tool name".into()))?;
    let args = params.get("arguments").cloned().unwrap_or(json!({}));

    match name {
        "search_code" => {
            let query = args
                .get("query")
                .and_then(|v| v.as_str())
                .ok_or_else(|| MethodError::InvalidParams("query required".into()))?;
            let top_k = args.get("top_k").and_then(|v| v.as_u64()).unwrap_or(5) as usize;
            let hits = server
                .search(query, top_k)
                .await
                .map_err(|e| MethodError::Internal(e.to_string()))?;
            let text = format_search_hits(&hits);
            Ok(json!({
                "content": [{"type": "text", "text": text}],
                "isError": false
            }))
        }
        "index_directory" => {
            let path = args
                .get("path")
                .and_then(|v| v.as_str())
                .ok_or_else(|| MethodError::InvalidParams("path required".into()))?;
            let reset = args.get("reset").and_then(|v| v.as_bool()).unwrap_or(false);
            let result = server
                .index_directory(PathBuf::from(path), reset)
                .await
                .map_err(|e| MethodError::Internal(e.to_string()))?;
            let text = format!(
                "Indexed {} files, {} chunks in {:.2}s",
                result.files_indexed, result.chunks_total, result.elapsed_seconds
            );
            Ok(json!({
                "content": [{"type": "text", "text": text}],
                "isError": false,
                "structuredContent": result
            }))
        }
        "get_stats" => {
            let stats = server
                .stats()
                .await
                .map_err(|e| MethodError::Internal(e.to_string()))?;
            let text = format!("Table: {}\nChunks: {}", stats.table, stats.chunks);
            Ok(json!({
                "content": [{"type": "text", "text": text}],
                "isError": false,
                "structuredContent": stats
            }))
        }
        other => Err(MethodError::InvalidParams(format!("unknown tool: {other}"))),
    }
}

fn format_search_hits(hits: &[crate::server::SearchHit]) -> String {
    if hits.is_empty() {
        return "(no results)".to_string();
    }
    let mut s = String::with_capacity(512);
    for (i, h) in hits.iter().enumerate() {
        let preview: String = h.content.chars().take(280).collect();
        s.push_str(&format!(
            "#{}  dist={:.4}  [{}:{}-{}]\n{}\n\n",
            i + 1,
            h.distance,
            h.file_path,
            h.start_line,
            h.end_line,
            preview
        ));
    }
    s
}
