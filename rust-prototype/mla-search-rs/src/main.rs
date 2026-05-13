mod chunker;
mod db;
mod license;
mod mcp;
mod server;
mod walker;

use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};

use crate::server::Server;

const DB_PATH: &str = "./data/lancedb";

#[derive(Parser)]
#[command(name = "mla-search-rs", version, about = "MLA Agent — Rust prototype")]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Verilmiş qovluğu walk et, faylları chunk et, LanceDB-yə yaz.
    Index {
        path: PathBuf,
        #[arg(long)]
        reset: bool,
    },
    /// LanceDB-də vector axtarış edib top-K nəticəni göstər.
    Search {
        query: String,
        #[arg(short = 'k', long, default_value_t = 5)]
        top_k: usize,
    },
    /// Cədvəl statistikası.
    Stats,
    /// MCP stdio server kimi işə düş (Claude Code üçün).
    Serve,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    // License enforcement (opt-in: yalnız MLA_LICENSE_KEY set-disə real check)
    let lic_config = license::LicenseConfig::from_env();
    let _guard = license::ensure_license(&lic_config).await?;

    let server = Server::new(DB_PATH).await?;

    match cli.cmd {
        Cmd::Index { path, reset } => {
            println!("Walking: {}", path.display());
            let r = server.index_directory(&path, reset).await?;
            println!(
                "✓ {} fayl → {} chunk, {:.2}s",
                r.files_indexed, r.chunks_total, r.elapsed_seconds
            );
        }
        Cmd::Search { query, top_k } => {
            let hits = server.search(&query, top_k).await?;
            if hits.is_empty() {
                println!("(nəticə yoxdur)");
                return Ok(());
            }
            for (i, h) in hits.iter().enumerate() {
                let preview: String = h.content.chars().take(120).collect();
                println!(
                    "\n#{}  dist={:.4}  [{}:{}-{}]\n  {}",
                    i + 1,
                    h.distance,
                    h.file_path,
                    h.start_line,
                    h.end_line,
                    preview
                );
            }
        }
        Cmd::Stats => {
            let s = server.stats().await?;
            println!("Cədvəl: {}\nChunks: {}", s.table, s.chunks);
        }
        Cmd::Serve => {
            mcp::serve(server::shared(server)).await?;
        }
    }
    Ok(())
}
