use std::path::{Path, PathBuf};

use ignore::WalkBuilder;

// Python `mla_constants.py` SUPPORTED_EXTENSIONS ilə uyğunlaşdırılmış siyahı.
// Step 3 üçün başlanğıc dəsti — sonra config faylına çıxaracağıq.
const SUPPORTED_EXT: &[&str] = &[
    "py", "rs", "ts", "tsx", "js", "jsx", "go", "java", "kt", "swift",
    "c", "cc", "cpp", "h", "hpp", "cs", "rb", "php", "scala", "sh", "ps1",
    "sql", "sol", "md", "json", "yaml", "yml", "toml",
];

// Əlavə exclude pattern-lər (`.gitignore`-dan başqa).
const EXTRA_EXCLUDE_DIRS: &[&str] = &[
    "node_modules", "target", "dist", "build", "__pycache__",
    ".venv", "venv", "env", ".env", ".idea", ".vscode", ".git",
    "chroma_db", ".fastembed_cache", "data", ".pytest_cache",
];

const MAX_FILE_SIZE_BYTES: u64 = 1024 * 1024; // 1 MB

#[derive(Debug, Clone)]
pub struct FoundFile {
    pub path: PathBuf,
}

/// `.gitignore` hörmət edən walker. Yalnız dəstəklənən uzantıları,
/// MAX_FILE_SIZE-dan kiçik faylları qaytarır.
pub fn walk(root: impl AsRef<Path>) -> Vec<FoundFile> {
    let mut builder = WalkBuilder::new(root.as_ref());
    builder
        .hidden(false) // .env və s. tutmaq üçün — exclude dir-lərlə filter
        .git_ignore(true)
        .git_global(true)
        .git_exclude(true)
        .standard_filters(true);

    for d in EXTRA_EXCLUDE_DIRS {
        // ignore crate-i override ilə əlavə pattern qəbul edir
        builder.add_custom_ignore_filename(".mla_ignore");
        let _ = d; // istinad saxlamaq üçün
    }

    let supported: std::collections::HashSet<&str> = SUPPORTED_EXT.iter().copied().collect();

    builder
        .build()
        .filter_map(|r| r.ok())
        .filter(|e| e.file_type().is_some_and(|t| t.is_file()))
        .filter(|e| {
            // Path-da exclude dir varsa atla
            let p = e.path();
            !p.components().any(|c| {
                let s = c.as_os_str().to_string_lossy();
                EXTRA_EXCLUDE_DIRS.contains(&s.as_ref())
            })
        })
        .filter(|e| {
            e.path()
                .extension()
                .and_then(|x| x.to_str())
                .is_some_and(|x| supported.contains(x))
        })
        .filter_map(|e| {
            let path = e.path().to_path_buf();
            let size = e.metadata().ok()?.len();
            if size > MAX_FILE_SIZE_BYTES {
                return None;
            }
            Some(FoundFile { path })
        })
        .collect()
}
