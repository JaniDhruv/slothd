## 🦥 slothd Pull Request

### Description
<!-- Briefly describe the feature, fix, or enhancement introduced in this PR. -->

### GitHub Copilot & Reviewer Checklist
- [ ] **Air-Gapped Privacy**: No un-gated external network requests added. All file contents and filenames remain local.
- [ ] **Non-Destructive & Reversible**: File moves are logged to SQLite `OperationLog` with support for `slothd undo`.
- [ ] **Gemma 3 Presentation**: All user-facing references, logs, and spinners display "Gemma 3".
- [ ] **Prior Labs TabPFN Integrity**: Any tabular feature additions update `extract_tabular_features` and tests.
- [ ] **CI & Style**: Passes `uv run ruff check .` and `uv run pytest tests/ -v -k "not test_idle"`.
- [ ] **Sentry Tracing**: Critical path spans instrumented with `trace_span()`.
