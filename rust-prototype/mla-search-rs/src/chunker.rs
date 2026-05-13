// Python `config.py`-yə uyğun fallback text splitter parametrləri.
// AST chunking sonradan (tree-sitter ilə) əlavə olunacaq — hazırda yalnız text-based.
pub const CHUNK_SIZE: usize = 1200;
pub const CHUNK_OVERLAP: usize = 200;

#[derive(Debug, Clone)]
pub struct Chunk {
    pub content: String,
    pub start_line: i32,
    pub end_line: i32,
}

/// Sliding window chunker. Sətr sərhədlərini hörmət edir,
/// multi-byte UTF-8 simvolların ortasında kəsmir.
pub fn chunk_text(text: &str) -> Vec<Chunk> {
    if text.is_empty() {
        return vec![];
    }

    let line_starts: Vec<usize> = std::iter::once(0)
        .chain(text.match_indices('\n').map(|(i, _)| i + 1))
        .collect();

    let total = text.len();
    let mut chunks = Vec::new();
    let mut start = 0usize;

    while start < total {
        let target = (start + CHUNK_SIZE).min(total);
        // Char boundary-yə snap (multi-byte UTF-8 üçün)
        let mut end = floor_char_boundary(text, target);

        // Sətr sərhədinə qədər geri çək (əgər ortada kəsmiş olsaq).
        if end < total {
            if let Some(nl) = text[start..end].rfind('\n') {
                end = start + nl + 1;
            }
        }
        // Heç bir sətr sərhədi tapılmadısa, char boundary-də saxla.
        if end <= start {
            end = floor_char_boundary(text, target);
            if end <= start {
                // Çıxılmaz: ən azı 1 char irəlilə
                end = next_char_boundary(text, start + 1);
            }
        }

        let content = text[start..end].trim_end_matches('\n').to_string();
        if !content.trim().is_empty() {
            chunks.push(Chunk {
                content,
                start_line: line_of(start, &line_starts),
                end_line: line_of(end.saturating_sub(1), &line_starts),
            });
        }

        if end >= total {
            break;
        }

        // Overlap geriyə, char boundary-yə snap
        let raw_start = end.saturating_sub(CHUNK_OVERLAP);
        let mut new_start = floor_char_boundary(text, raw_start);
        // Overlap edəndə də sətr sərhədinə düz
        if new_start > 0 {
            if let Some(nl) = text[..new_start].rfind('\n') {
                new_start = nl + 1;
            }
        }
        // Sonsuz loop qarşısı: ən azı 1 byte irəlilə
        if new_start <= start {
            new_start = end;
        }
        start = new_start;
    }

    chunks
}

#[inline]
fn floor_char_boundary(s: &str, mut idx: usize) -> usize {
    if idx >= s.len() {
        return s.len();
    }
    while idx > 0 && !s.is_char_boundary(idx) {
        idx -= 1;
    }
    idx
}

#[inline]
fn next_char_boundary(s: &str, mut idx: usize) -> usize {
    let len = s.len();
    if idx >= len {
        return len;
    }
    while idx < len && !s.is_char_boundary(idx) {
        idx += 1;
    }
    idx
}

fn line_of(char_idx: usize, line_starts: &[usize]) -> i32 {
    // 1-indexed sətr nömrəsi
    match line_starts.binary_search(&char_idx) {
        Ok(i) => (i as i32) + 1,
        Err(i) => i as i32,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_text_yields_no_chunks() {
        assert!(chunk_text("").is_empty());
    }

    #[test]
    fn small_text_one_chunk() {
        let text = "hello\nworld\n";
        let chunks = chunk_text(text);
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].start_line, 1);
    }

    #[test]
    fn large_text_multiple_chunks_with_overlap() {
        let line = "abcdefghij".repeat(20); // 200 char
        let text = (0..50).map(|_| line.clone()).collect::<Vec<_>>().join("\n");
        let chunks = chunk_text(&text);
        assert!(chunks.len() >= 2);
        for w in chunks.windows(2) {
            assert!(w[1].start_line <= w[0].end_line + 5);
        }
    }

    #[test]
    fn multi_byte_utf8_does_not_panic() {
        // em-dash (3 byte), Azərbaycanca hərflər (ə = 2 byte)
        let chunk_filler = "ə".repeat(CHUNK_SIZE);
        let text = format!("Header — başlıq\n{}\nmoreText", chunk_filler);
        let chunks = chunk_text(&text);
        assert!(!chunks.is_empty());
    }
}
