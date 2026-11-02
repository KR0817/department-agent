# Project context

Created: 2026-10-27

The user requested a public Git repository for the integrated Department Agent. This repository is a fresh source-only distribution, not a mirror of a private backup or its Git history.

Three modules share a clinical-session-protected host: clinical document review and archival, source-bound public-literature questions, and the complete MingYiRx prescription workspace. The latest UI is retained. Default public data is explicitly synthetic and does not demonstrate clinical extraction accuracy.

Original project source licenses and third-party notices must be preserved. Literature, private derived reports, original clinical exports, credentials, model weights and private operation logs are not redistributable payloads for this repository.

The public demonstration must use independently generated fixtures and relative paths, preserve full prescription functionality and avoid dependencies on the author's machine. Optional real-model/corpus configuration is documented separately from the offline smoke test.

## Public release decisions

- The integrated source uses AGPL-3.0-only, matching the incorporated ClinData Relay license. MIT and OFL notices remain attached to their components.
- The synthetic knowledge path is explicit and deterministic; it is not model inference. Frozen literature and historical corpus-bound benchmarks are excluded. Tests that require the missing frozen corpus report a skip.
- The 14 prescription resources are generated under ignored work directories. Existing renderers supply the aggregate, clinical, exact-prescription and inheritance views. The report and report CSVs are invented display fixtures.
- The launcher uses only loopback services, per-run persistence and an operating-system file lock. It stops only processes it started. The integration smoke exercises clinical review, prescription revision persistence and a restart without invoking a model.
- The source link points to the matching public release tag. Publishing a modified service requires an updated source offer.
- Windows CI may return an 8.3 short path for temporary directories. Tests that mock a checkout root must resolve that root, matching production path canonicalization; the private-output location and Git-ignore guards remain unchanged.

## Workbench UI optimization - 2026-10-29

- The approved Verda-inspired concept is implemented on the local UI branch using the existing vanilla frontend. The desktop rail is 220px, the tablet rail is 76px, and phones use an accessible modal menu. Keep the existing deep-green action color and clinical semantic colors.
- Clinical source review reuses one viewer with per-field entry points, safe exact-text highlighting, wide-screen pinning, focus return and narrow-screen modal fallback. Review decisions, default acceptance and explicit archival semantics remain unchanged.
- Knowledge sources deliberately disallow framing. Keep the original protected standalone reader and show excerpts/provenance in the answer card; do not weaken CSP to embed source pages.
- The prescription workspace retains its original iframe and all 14 generated assets. Expanded canvas mode must preserve nested iframe state, respect consumed Escape events and remove owned listeners on logout. Imported collections and annotation drafts retain their distinct persistence semantics.
- Browser evidence belongs in ignored work directories. Edge full-page screenshots can transiently report a 1px viewport; use viewport screenshots for open dialogs to avoid changing responsive UI state during capture. Repeated identical clinical uploads are idempotent; browser checks should use the returned filename.
- Verification records for this iteration are summarized in docs/UI-Optimization-Verification.md. The local synthetic preview is separate from private live services and backups. The user subsequently authorized publishing the source update to GitHub; version 0.1.1 and its matching source tag identify the UI iteration. Private runtime artifacts remain excluded.

## Local department assistant - 2026-11-02

- The user authorized implementing the article-based improvement design. The named GitCC repository remained inaccessible; no upstream code or license was imported. This iteration adds local source changes and an isolated synthetic preview, not a Git publication or private-service replacement.
- `department_assistant.py` reuses the existing parser and authenticated full workspace. Keep public knowledge selection separate from case/draft content. Bounded keyword routing asks for an explicit task when ambiguous; case search is lexical over the current account's committed records, not a semantic or clinical similarity score.
- Assistant drafts use a separate append-only SQLite store under the run data directory, scoped to the host account. Preserve optimistic revision checks, identical-retry handling and explicit saves. Context contains the last search/revision and public source selection; older drafts without context receive empty defaults.
- Supplemental observations retain original source records, status and origin. A fresh explicit review is required for quick-analysis handoff. Original business archival, collection commit and all prescription pages/downloads remain in their existing workflows.
- `assistant.js` clears sensitive state and aborts owned requests on logout. Bind response handling to session, view, task identity and input revision. Unsaved navigation state remains in memory; browser-close warns, and persisted drafts resume from the task list.
- Evidence belongs in ignored `work/assistant-20261102`. Verification is documented in `docs/Assistant-Verification.md`; software checks do not establish medical reasoning or model accuracy. Global memory was not modified.

## Source-informed assistant extension - 2026-11-02

- The user supplied `agent-chinese-med.zip` and authorized source-grounded design followed by implementation. Archive SHA-256: `17ca1d709bdf2a2c693913ba8d3eb2b406f6ed9f1d9dd6c3ae5fced86544f328`. Inspection followed the active `agent.tcm_service` path. The backend README states MIT, but no application-level license file is supplied. All additions are independently implemented; upstream source, prompts, assets and corpora remain outside this repository.
- Borrow guided information collection, resumable work and explicit operation states. Keep the six existing supplemental fields and durable account-scoped SQLite store. Missing, recorded and unavailable counts describe documentation status, never clinical sufficiency.
- History endpoints paginate 20 immutable revision summaries and read a selected version. Recovery loads a previewed version into a dirty current draft; explicit saving appends using the current optimistic revision. Unrelated edits and concurrent saves must not be overwritten.
- Cancellation aborts browser waiting and discards late responses for planning, recognition and search; it does not guarantee server cancellation. Saving retains existing idempotent retry semantics and is not cancellable.
- Upstream retrieval error fallbacks can return simulated papers/cases; do not adopt them. Do not add graph databases, model inference or credential management without an actual validated use case.
- Current source-review verification is separate from the earlier article-based iteration, under ignored `work/source-review-20261102`. Existing private services remain untouched. Global memory was not modified.

## Release checkpoint - 2026-11-02

- The user explicitly requested publishing the completed version before React/LangGraph work. Prepare v0.2.0 from the current assistant implementation, retaining the FastAPI/vanilla frontend architecture and all original modules. React and LangGraph implementation has not begun and is outside this release.
- Keep the package version, lock metadata and source-offer tag aligned. Publish only reviewed source and documentation; reference archives and private/runtime payloads remain excluded. Release notes are in docs/Release-v0.2.0.md. Add the dependency-free Node assistant state suite to CI.
