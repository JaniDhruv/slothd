---
name: audit-privacy
description: "Audit slothd codebase or a pending diff for air-gap compliance and network leak prevention"
---

# slothd Air-Gap & Privacy Compliance Audit

You are auditing code in `slothd` to enforce its foundational promise: **air-gapped, zero-cloud data leakage by default.**

## Audit Checklist
Inspect the target file, module, or git diff against these mandatory constraints:

1. **No Silent Cloud Outbound Calls**:
   - Are there any `requests`, `httpx`, or socket calls that transmit filenames, file contents, or directory paths to external endpoints without an explicit opt-in check?
   - Any external integration (such as SerpApi in `enricher.py` or ElevenLabs in `elevenlabs.py`) must be guarded by a configuration key check AND an explicit CLI flag/prompt.

2. **Local Inference by Default**:
   - All AI classification must target local Ollama (`http://localhost:11434`).
   - Does `is_ollama_online()` guard inference batches to prevent hangs when Ollama is offline?

3. **No Unsanitized Error Reporting**:
   - Verify that Sentry breadcrumbs or tags in `sentry_tracing.py` do not attach raw file contents or sensitive personal documents.

4. **Transient Cache Isolation**:
   - Are vector embeddings stored locally (Tiger Data Docker or SQLite fallback) rather than transmitted to cloud vector APIs?

Produce an **Air-Gap Audit Report** detailing:
- [PASS / FAIL] status for each checklist item
- Any leaked tokens or endpoints discovered
- Suggested remediation diffs
