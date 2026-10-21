# GitHub Copilot Instructions for slothd

You are assisting with development on **slothd (The Sloth Daemon)**, an air-gapped, local-first AI file organizer and daemon that organizes user files when their system is idle.

---

## 1. Architectural Principles

1. **Air-Gapped & Local-First by Default**:
   - Never send user filenames, file contents, or personal directories to external third-party cloud APIs by default.
   - All AI classification defaults to **local Gemma 3** running via Ollama (`http://localhost:11434`).
   - External integrations (such as **SerpApi** for web grounding or **ElevenLabs** for voice summaries) are strictly **opt-in** via explicit CLI flags (`--enrich-online`, `slothd briefing`) or user confirmation prompts.

2. **Non-Destructive Operations & Reversibility**:
   - `slothd organize` is a **dry-run preview by default**. Never move files unless `--go` is passed or explicitly confirmed by the user.
   - Every file move MUST be logged to the SQLite operation log (`operations.db`) so `slothd undo` can cleanly reverse the batch.
   - Always preserve original file creation and modification timestamps (`st_mtime`, `st_ctime`).

3. **Modern Terminal Design (Vercel / Vite / Claude Code Aesthetic)**:
   - All visual and terminal presentation logic belongs in `slothd/ui.py`. Keep `slothd/cli.py` focused on command orchestration.
   - Use left-aligned guide rails (`│`, `┌`, `├`, `└`) and semantic unicode glyphs (`◆`, `◇`, `✔`, `▲`, `✖`).
   - For interactive prompts, use `InquirerPy` styled with `ui.get_style()` to ensure type compliance with `InquirerPyStyle`.

---

## 2. Technology Stack & Coding Standards

- **Language**: Python 3.10+ (modern typing: `list[str]`, `dict[str, Any]`, `X | None`).
- **Package Management**: Managed via `uv` (`pyproject.toml`).
- **CLI Framework**: `click` with custom `SlothdGroup` error handler.
- **Terminal UI**: `rich` Console, Tables, Progress, and Text assemblies.
- **AI Classification**: `ollama` with Pydantic grammar schemas (`format=FileClassification.model_json_schema()`) to ensure 100% valid JSON without markdown wrapping.
- **Vector Search & Embeddings**: Tiger Data PostgreSQL + `pgvector` with HNSW indexing and cosine similarity (`nomic-embed-text`).
- **Observability**: `sentry-sdk` with custom `trace_span(op=..., description=...)` for agent tracing and latency benchmarking.

---

## 3. Testing Conventions

- Run tests using `pytest tests/ -v`.
- Tests for offline services should mock network calls to Ollama, Tiger Data, ElevenLabs, and SerpApi.
- Idle loop tests (`test_idle`) simulate sleep intervals and should be deselected during fast runs: `pytest -k "not test_idle"`.
- All code modifications must pass `ruff check .` with zero errors.
