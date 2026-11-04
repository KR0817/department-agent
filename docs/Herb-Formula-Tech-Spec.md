# Herb and formula consultation

Date: 2026-11-03

## Outcome and scope

Add herb and formula consultation to the existing department knowledge page.
Preserve its literature mode, original fulltext connection, source readers and
clinical-session boundary. Use the installed local model; do not connect patient
records, publish source changes, download models or copy the original corpus.

The current rheumatology corpus is not a complete materia medica database.
Generated educational content and retrieved source passages must have separate
labels. A matching source identifier does not establish claim support. Missing
retrieval must be visible and must never produce invented bibliography.

## API contract

- `GET /api/department/knowledge/catalog` retains existing fields and adds
  `consultation`: enabled, provider, model and input scope. Configuration is
  server-side, never accepted from browser requests.
- `POST /api/department/knowledge/consult`: JSON object with exactly `kind`
  (`herb` or `formula`), `subject` (1-80 characters), `question` (1-1000), `disease`
  (`all`, `sjd`, `ra`, `gout`), `source_id` and `index_sha256`, plus optional
  `provider` (`local` default, `deepseek`, `kimi`) and `public_topic_confirmed`
  (required true for API providers). The same catalog
  binding and source scope as literature extraction apply. Invalid requests and
  stale indexes fail before any inference.
- A successful response contains `status=answer`, kind, subject, model/provider,
  model_called, generated sections, server-owned source metadata/quotes/locators,
  evidence availability, an index digest and elapsed time. All generated sections
  remain model content pending human review; source association is not support
  verification. Failure statuses include busy, model_disabled, model_unavailable,
  invalid_model_output and source_unavailable; no synthetic medical fallback.
- Consultation and extraction share a nonblocking model lock in the adapter.
  No request text, completion, account identifier or source text is logged/saved.

## Implementation

1. Add a small local LLM adapter. Reuse the original isolated Docker transport or
   the existing bounded numeric-loopback Ollama HTTP client. Check installed GGUF
   metadata and reject cloud-backed models. Configuration names:
   `DEPARTMENT_LLM_TRANSPORT` (`docker` default or `ollama`),
   `DEPARTMENT_LLM_MODEL` (`qwen3:14b` default), and
   `DEPARTMENT_LLM_ENDPOINT` (numeric loopback, Ollama mode only).
   The user subsequently requested DeepSeek and Kimi. Add their official HTTPS
   Chat Completions endpoints with server-only `DEEPSEEK_API_KEY` and
   `MOONSHOT_API_KEY`, explicit UI provider selection, bounded responses and
   sanitized errors. No retries or provider fallback. Remote requests contain
   only the subject and current public question; local passages stay local.
   Reject identifying patterns and require the public-topic acknowledgment before
   API dispatch. This is an additional boundary, not a validated PHI detector.
2. Add consultation orchestration using the already-configured original index.
   Match the explicit subject in sources/chunks before ranking; include complete
   bounded passages and verify source integrity before/after inference. Return
   source metadata from the server only. Use a strict structured output schema
   for identity, traditional properties/composition, uses/principle, cautions and
   uncertainty. Unknown identities should request clarification.
3. Add three consultation modes to the existing knowledge page. Retain question
   and source controls, loading/error states, safe text rendering and source
   links. Discard late responses after changes of mode, input, scope or session.
   Cancellation stops browser waiting; server work may still finish.
4. Add tests, configuration documentation and a generic project-memory note.
   Runtime receipts and local launch settings remain ignored.

## Clinical and trust boundaries

This is professional educational consultation, with no patient-specific
prescribing or automatic medication changes. Prompts and bounded server checks
handle personal dosing and urgent ingestion/adverse-event requests separately.
No generated bibliography, external links, tool execution or automatic clinical
approval. UI notices remain concise. These controls are not a validated medical
safety classifier. New inputs and source passages are untrusted data.

## Verification

- Unit/integration tests for request validation, stale binding, shared busy lock,
  local-only transport, model failures, malformed/truncated output, unknown source
  IDs, evidence-free replies, source integrity and selected-source scope.
- Frontend regression for mode switching, cancellation, stale responses, logout
  and safe rendering. Existing knowledge and assistant tests remain green.
- Actual local-model requests for one herb and one formula, plus the original
  literature question. Record software behavior, not clinical accuracy claims.
- Browser checks at desktop and mobile sizes: modes, sources, answers, errors,
  readable layout and no external requests. Verify all 229 original fulltexts
  remain connected and preserve existing run data on the current preview restart.
- Public-source packaging scan. No Git publication in this task.

## Primary API references

Executed checks and remaining API limitations are recorded in
[Herb-Formula-Verification.md](Herb-Formula-Verification.md).

- https://docs.ollama.com/api/chat
- https://docs.ollama.com/capabilities/structured-outputs
- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/guides/json_mode/
- https://platform.kimi.com/docs/api/chat
