# Changelog

All notable changes to the Tokengram VS Code extension are documented here.

## 0.2.7

**Your savings number may look smaller — that's intentional, and it's good news.**

- **Evidence-based savings (proven, not estimated).** Tokengram now counts a
  token as "saved" only when it has hard evidence for it — a search that
  answered without opening the file, a blocked full-file read, a targeted
  edit. Earlier versions included heuristic estimates that inflated the
  total. The new number is smaller, but it is one you can verify against
  your own usage. *We only count savings we can prove.*
- **Leaner search results.** `search_code` responses are now deduplicated
  (identical chunks from copied files return once) and long chunks are
  capped — search results take less space in your assistant's context, so
  the savings aren't eaten back in long sessions.
- **Clearer status bar.** A fresh install shows "ready" instead of a
  confusing "0.0k saved"; the tooltip explains what is (and isn't) counted.

## 0.2.0

- Smarter search guidance — the assistant is steered toward semantic code
  search first, cutting token usage on broad "where/how" questions.
- Faster cold start and lower memory use for background indexing.
- General stability and reliability improvements.

## Earlier releases

Tokengram has shipped continuous performance, stability, and indexing
improvements across the 0.1.x line — faster startup, lower memory use,
more reliable incremental re-indexing, and a clearer status bar.
