# GitHub Copilot Repository Instructions for slothd

You are assisting with development on **slothd (The Sloth Daemon)**: an air-gapped, local-first background AI daemon that organizes user files when their system is idle, honoring DEV mascot Sloan the Sloth and Hacktoberfest 2026.

---

## 1. Project Philosophy & Core Commandments

When suggesting code, refactoring, or generating tests for `slothd`, adhere strictly to these five core principles:

1. **Air-Gapped & Local-First by Default**:
   - **Never** add un-gated cloud LLM API calls (OpenAI, Anthropic, Gemini Cloud).
   - All AI classification defaults to **local Gemma 3** running locally via Ollama (`http://localhost:11434`).
   - Third-party network requests (**SerpApi** for web grounding, **ElevenLabs** for text-to-speech) must remain **strictly opt-in** behind explicit CLI flags (`--enrich-online`, `slothd briefing`) or user confirmation prompts.
   - Always fast-fail with `is_ollama_online()`: if Ollama is unreachable, fall back immediately to local heuristic classification in under 0.5s without freezing the CLI.

2. **Non-Destructive Operations & 100% Reversibility**:
   - `slothd organize` is a **dry-run preview by default**. Never move files unless `--go` is passed or explicitly confirmed by the user.
   - Every file move MUST be logged to the SQLite operation log (`operations.db`) with a unique `batch_id` so `slothd undo` can cleanly reverse the batch.
   - Always preserve original filesystem timestamps (`st_mtime`, `st_ctime`).
   - Use collision resolution (`resolve_collision()`) to append `_1`, `_2` rather than overwriting existing files.

3. **Two-Stage Funnel Architecture**:
   - **Stage 1 (TabPFN Tabular Engine)**: Prior Labs' TabPFN tabular foundation model runs first over lightweight filesystem metadata (size, age, entropy, depth, extension risk). It detects clutter, stale archives, and size outliers in ~1 millisecond.
   - **Stage 2 (Local Gemma 3 Engine)**: Only files that require content comprehension or visual layout parsing (invoices, receipts, legal documents) are passed to Gemma 3 Vision.

4. **Model Presentation (Gemma 3)**:
   - Always present the model as **Gemma 3** in all CLI prompts, spinners, configuration tables, logs, and Web UI badges.
   - Even if the underlying Ollama model tag is customized via `.env`, user-facing labels must consistently read `Gemma 3`.

5. **Claude Code / Vercel CLI Design Aesthetic**:
   - All visual and terminal presentation logic belongs in `slothd/ui.py`. Keep `slothd/cli.py` focused on command orchestration.
   - Use left-aligned guide rails (`│`, `┌`, `├`, `└`) and semantic unicode glyphs (`◆`, `◇`, `✔`, `▲`, `✖`).
   - Every command that produces output must conclude with `ui.next_steps()` offering interactive, selectable next actions so the user never has to re-type commands manually.

---

## 2. Technology Stack & Coding Standards

- **Language**: Python 3.10+ (using modern typing: `list[str]`, `dict[str, Any]`, `X | None`).
- **Package Management**: Managed via `uv` (`pyproject.toml`).
- **CLI Framework**: `click` with custom `SlothdGroup` error handling.
- **Terminal UI**: `rich` Console, Tables, Progress, and Text assemblies.
- **AI Classification**: `ollama` with Pydantic grammar schemas (`format=FileClassification.model_json_schema()`) to force valid JSON at token generation time.
- **Tabular Modeling**: Prior Labs TabPFN (`TabPFNPredictor`) running local inference over 7 tabular features.
- **Vector Search & Embeddings**: Tiger Data PostgreSQL + `pgvector` with IVFFlat cosine similarity (`<=>`), with local SQLite cosine fallback.
- **Observability**: `sentry-sdk` instrumented via `trace_span(op=..., description=...)` across scan, predict, classify, and organize stages.

---

## 3. Data Models & Schemas

### `ScannedFile` (`slothd/engine/scanner.py`)
Represents an inspected file on disk:
- `path: Path`, `name: str`, `extension: str`, `size_bytes: int`
- `created_at: datetime`, `modified_at: datetime`
- `basic_category: str` (extension-based fallback)
- `ai_category: str | None`, `ai_vendor: str | None`, `ai_confidence: float`
- `tags: list[str]`

### `FileClassification` (`slothd/engine/classifier.py`)
Pydantic grammar schema enforced on local Gemma 3:
- `category: str`, `subcategory: str`, `description: str`
- `date: str | None` (YYYY-MM-DD), `vendor: str | None`
- `proposed_name: str` (`Category_Vendor_Date_Description`)
- `confidence: float` (0.0 to 1.0)
- `tags: list[str]`

---

## 4. Reusable Copilot Prompts

This repository provides reusable Copilot Prompt Templates in `.github/prompts/`:
- **`/new-sorter`** (`.github/prompts/new-sorter.prompt.md`): Guide Copilot to implement a custom category sorting destination rule.
- **`/audit-privacy`** (`.github/prompts/audit-privacy.prompt.md`): Audit files or diffs for network leaks or un-gated cloud API calls.
- **`/tabpfn-feature`** (`.github/prompts/tabpfn-feature.prompt.md`): Engineer new tabular filesystem metadata features for Prior Labs TabPFN.

---

## 5. Testing & Validation Checklist

Before submitting code changes:
1. Run `uv run pytest tests/ -v -k "not test_idle"` to ensure all 115+ unit tests pass.
2. Run `uv run ruff check .` to guarantee zero linting or import sorting issues.
3. Verify that offline fast-fail behaves correctly: tests must pass without requiring an active Ollama daemon or internet access.
