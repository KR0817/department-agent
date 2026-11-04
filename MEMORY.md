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

## React consultation and LangGraph - 2026-11-02

- The user requested adding React and LangGraph after the v0.2.0 checkpoint was published. Development source is 0.3.0.dev0. This iteration adds an independently built React/TypeScript workspace at `/#consultation`; the original assistant and three business workspaces remain available. It is an incremental frontend migration, not a claim that all legacy pages use React.
- `clinical/consultation_graph.py` compiles a real LangGraph StateGraph with recognition, missing-field assessment, question/source branches and explicit review. It reuses the parser and six source-bound supplement fields. It performs no language-model inference or automatic diagnosis/prescribing. Disable LangSmith tracing explicitly even if host environment settings request it.
- Each turn reconstructs graph state from the validated current draft. Durable state remains in the existing account-scoped append-only SQLite draft store. Do not introduce a parallel checkpoint database or describe this as LangGraph interrupt/checkpointer persistence. Restoring history still appends a new version; handoff never grants clinical archival approval.
- React retains unsaved state across host navigation, reconciles in-flight saves, rejects stale read responses and clears on logout. Keep CSS/JS local and preserve the host CSP/session/origin protections. Production uses the existing Python host; Node.js 24+ builds assets under ignored `clinical/static/consultation/` with `npm --prefix frontend ci --ignore-scripts` and `npm --prefix frontend run build`.
- Frontend and graph dependencies are locked; MIT notices for React/React DOM/Scheduler and LangGraph are retained. Public-source scanning accepts frontend source but rejects generated bundles and dependency directories. CI now installs/builds/tests the frontend before backend checks.
- The isolated synthetic preview is separate from existing services. Evidence is recorded under ignored `work/react-langgraph/` and summarized in `docs/React-LangGraph-Verification.md`. The public v0.2.0 tag is unchanged; no new Git publication or private-service replacement was requested in this iteration. Global memory was not modified.

## Restore the existing local literature library - 2026-11-03

- The user expects the existing literature library in the current local workbench. A feature preview using `synthetic-demo` must not be presented as a replacement for that connected workbench. Public checkout defaults remain synthetic; local launches must explicitly select `fulltext` and the original knowledge root.
- The restored local catalog has 230 library records, 229 local full texts, 228 retrieval-eligible sources and 5,801 chunks. These are different counts and should retain their labels. Literature content, model weights and local configuration remain outside Git.
- Preserve the existing run name and data directory when correcting a preview connection. The local-only launcher and verification receipts are under ignored `work/`. Future preview changes must verify the library identity and an actual source-bound answer, not merely the synthetic endpoint or UI rendering.
- Docker Desktop was stopped and subsequently blocked by a stale runtime socket. Its socket-only directory was preserved under a timestamped name before restarting the existing runtime; no model, database, credential or corpus was deleted. The existing isolated model container and local qwen3:14b inference were verified. See the local repair receipt for machine-specific details; do not repeat runtime repairs without checking the current cause.

## Herb/formula consultation and provider APIs - 2026-11-03

- The user requested model invocation code and herb/formula consultation within Knowledge Q&A, then explicitly added DeepSeek and Kimi API support. `department_consultation.py` owns the structured educational response and source association; `department_llm.py` owns isolated local and official HTTPS transports. The original extractive literature mode stays available.
- Local consultation can use complete matching passages from the existing index. Source matching is literal-name plus lexical ranking, not comprehensive bilingual materia medica retrieval. Model sections and source passages have separate provenance; a linked passage is not verified claim support. Preserve explicit no-matching-evidence and clarification states.
- API selection is explicit. Credentials stay in server process environment; `Start-WithApi.ps1` supports hidden local entry without credential files or command-history values. API requests receive only the named subject and current acknowledged public question, never the local corpus, saved drafts or patient context. No automatic retries, provider fallback or model downloads.
- Keep source hash binding, auth/origin checks, bounded responses, shared inference lock, sanitized failures and frontend stale-response/cancellation guards. Numerical dosing instructions and generated bibliography are rejected; these software guards do not establish medical safety or accuracy.
- Real local herb and formula probes returned five-section answers. An initial overbroad clarification behavior was corrected in the prompt. API transport tests use synthetic responses; real Kimi validation returned an authentication failure and DeepSeek lacked configuration in the tested environment. Do not describe either external provider as successfully connected until credentials and a real request are verified.
- Verification receipts and original corpus remain outside Git under ignored `work/`. The existing local workbench run/data and fulltext configuration are retained. No publication or global-memory update was performed in this iteration.

## Local expert collaboration - 2026-11-03

- The approved first stage adds bounded herb/formula role collaboration inside Knowledge Q&A. Preserve the original literature mode and single-model provider paths. Dynamic intake and local case discussion remain separate stages. Sequential local calls share the knowledge-model lock; no external provider or tracing is used for collaboration.
- A compiled LangGraph runs independent TCM-reference and evidence inputs, then pharmacy review and synthesis. Current roles share one model, so agreement is not independent verification. Keep role failure, insufficient evidence, review concerns and source changes visible; never replace failed roles with simulated answers.
- Real-model probes exposed invented book quotations, formula-to-component extrapolation and unreliable transcription. General roles now use schemas without citation fields. Evidence selects known passage IDs; the server attaches complete frozen originals. Exact source identity and name presence do not prove semantic support. Keep model knowledge, source text and human support review separate.
- Keep bounded generation, complete-passage omission counts, model/prompt/input/index/result receipts and transport-failure short circuiting. Do not truncate source qualifications to improve apparent model success. A comprehensive drug knowledge base and clinician-reviewed accuracy benchmark remain needed before stronger medical claims.
- Collaboration jobs are owner-scoped process memory with bounded retention and cooperative cancellation. Explicit JSON download records review acknowledgment, never clinical approval. It is not an archive or checkpoint resume. Browser polling must cancel known jobs and discard stale responses on input, scope, view or session changes.
- Verification is described in docs/Expert-Collaboration-Verification.md; local prompts/results and screenshots stay in ignored work directories. Existing run/data and original library must remain connected during local cutover. No Git publication or global-memory update is included in this iteration.
- Final local herb/formula probes completed the workflow, but manual review still found incorrect formula-component/effect attribution. Keep the UI labeled as a local trial; clinical content acceptance has not passed. The original literature mode was independently verified after cutover with three source-bound extracts, and the five original library/index/manifest hashes were unchanged.

## Kimi 3.1 connection verified - 2026-11-05

- The user confirmed a China open-platform key and requested Kimi 3.1. After masked local entry, the official model-list check passed. The current local workbench uses the process override `DEPARTMENT_KIMI_MODEL=kimi-k3.1-pro`; the source package's default remains K2.6.
- A real public-topic herb consultation returned status `answer`, five sections, and upstream model `kimi-k3.1-pro` in 24.586 seconds. The original catalog still contained 229 full texts. This supersedes the previous Kimi authentication-failure snapshot for this running process; it does not establish clinical correctness or future credential validity.
- Keep API calls limited to the acknowledged public question. Local corpus and patient context are excluded. Expert collaboration remains local-only. No key was written to a file, document, command argument or Git; closing the launcher ends the process-only configuration. Non-secret verification receipts remain under ignored work directories. No Git publication or global-memory update was performed.

## Hybrid local and Kimi experts - 2026-11-05

- The user clarified that expert collaboration should use the local model and Kimi together. Workflow v2 keeps local-only as default and adds an explicit local + Kimi choice. A bounded parallel reference node runs Kimi TCM knowledge alongside local evidence; local pharmacy and synthesis join their validated reports. Maximum one Kimi and three local calls; no automatic retry or provider fallback.
- Kimi receives only kind, subject and the acknowledged public question with a fixed prompt/schema. Corpus passages, source metadata, prior reports and patient context remain local. Keep per-role model/provider receipts, sanitized failures, source integrity, cooperative cancellation, ownership, disabled tracing and human-review labels. A Kimi transport failure must not suppress otherwise available local roles.
- Reuse the existing official HTTPS transport and process-only model configuration. Do not extract a key from an old service to restart a deployment. Windows venv child services can outlive their launcher: verify the recorded host executable/arguments and listener ownership before stopping task-owned services; perform this preflight before prompting for a key.
- Implementation and verification are described in docs/Hybrid-Expert-Tech-Spec.md and docs/Hybrid-Expert-Verification.md. Module suites, state suites, browser checks and integration smoke passed. After controlled restart and restoration of the stopped Docker engine, live hybrid inference completed all four roles in 140.643 seconds with one Kimi 3.1 and three local calls; the reference calls overlapped. The 229-entry catalog and five original corpus-file hashes were unchanged. Operational receipts stay in ignored work directories. No Git publication or global-memory update is included.

## All Kimi 3.1 experts - 2026-11-05

- The user explicitly authorized sending selected public literature excerpts and derived role reports to Kimi so all four experts can use Kimi 3.1. This supersedes the public-question-only boundary only for the separately selected all-Kimi mode, with public-topic and public-evidence acknowledgments. Local-only and hybrid paths retain their prior boundaries. Patient records, private cases, source paths and whole-library exports remain excluded.
- Workflow v3 accepts expert-only `expert_mode=all_kimi` and `public_evidence_confirmed=true`; require `provider=kimi` and exact model `kimi-k3.1-pro`. TCM/evidence run concurrently, followed by pharmacy and synthesis. Local model availability is not required. Public PMID/DOI source identities, complete-passage budgets, identity-marker checks and field allowlists bound external inputs. Source retrieval, integrity and exact-quote attachment remain local; agreement is not independent validation.
- Live all-Kimi verification completed four API roles in 64.789 seconds, with one selected public passage supplied to evidence/pharmacy and no local inference. The original 229-source library, combined-index identity and five corpus-file hashes were unchanged. Backend, state and browser checks are documented in docs/All-Kimi-Expert-Verification.md. No clinical-accuracy claim or Git publication is included.
- The current local masked-input launcher retains process-only configuration across up to three owned service restarts. It stores no credential file; keep that window open during use. Source, reports, operational receipts and corpus data remain separately scoped. Global memory was not modified.

## v0.3.0 publication and introduction - 2026-11-05

- The user explicitly requested updating Git with the latest completed version, creating an introduction document and listing local directories. This authorizes publishing the curated source update to the existing repository with a v0.3.0 tag. Preserve all earlier commits and private source/runtime boundaries.
- Version 0.3.0 includes the React intake, LangGraph workflows, herb/formula providers and three expert modes. Align package/lock metadata and the UI source offer. Public English product documentation is in docs/Project-Overview.md and release scope/checks are in docs/Release-v0.3.0.md.
- Chinese Word/Markdown introduction, local directory map and source inventory belong in ignored outputs/v0.3.0. They may name this machine's paths and must stay out of Git. The original corpus, live configuration, runtime stores and private backups remain separate. No global memory update is included.
