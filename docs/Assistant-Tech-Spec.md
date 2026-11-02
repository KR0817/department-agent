# Department assistant

Date: 2026-11-02
Baseline: v0.1.1 / ac18fad7772565337705bcc05679b04fab6bf817

## Outcome

Add a bounded task entry to the existing workbench. Connect local record intake,
missing-information collection, public knowledge selection, saved-case search and
the complete prescription workspace. Reuse the current parser and review flow.
No new dependency, external inference, source repository transplant or live-data
migration is required. Preserve every original prescription page and download.

## Contract

All routes live under `/api/department/assistant` and inherit host authentication,
Origin enforcement and no-store responses. The authenticated account exclusively
owns its drafts and prescription collection. The demo has one synthetic operator.
Inputs reject unknown keys, invalid types, non-finite values and excessive sizes.

- `POST /plan`: `{instruction, task}`. `task` is `auto`, `intake`, `knowledge`,
  `cases` or `prescriptions`. Deterministic keyword routing returns possible tasks;
  multiple matches and unknown requests require explicit selection. This is task
  routing, not medical reasoning. No tool or external request is executed.
- `POST /prepare`: a draft body. Reuse `analysis/recognize` for labeled text/CSV/JSON.
  Return original evidence, candidate records, supplement provenance and missing
  template fields. Unsupported free prose remains unresolved. Never infer values.
- `GET /drafts`, `GET /drafts/{id}`, `POST /drafts/{id}`. Save payload:
  `{expected_revision, draft}`. Draft schema `department-task-v1` contains
  `instruction`, `task`, `data_origin`, `text`, `supplements`, and a bounded `context`
  containing saved-case query/revision and public knowledge category/source ID.
  Older local drafts without context receive empty defaults. Each supplement
  identifies an original record and one of symptoms/tongue/pulse/syndrome/principle/
  prescription, with `value`, `status` (recorded/not_asked/unavailable) and `origin`
  (patient/clinician/history/operator/unknown). Explicit saving appends a SQLite
  revision. Stale updates return 409; identical retries return the committed result.
  Lists contain only latest summaries. No draft deletion or automatic clinical save.
- `GET /library`: categorized public inventory. Explicit metadata controls type;
  existing literature and synthetic fixtures retain their actual identities. Empty
  classics and formula categories remain empty. Private cases use a separate route.
- `POST /cases`: `{query}`. Search only the authenticated user's explicitly committed
  prescription records. Return bounded lexical matches, source hashes, fields and
  current collection revision. No nonce, global corpus or patient-identity union.

Drafts are separate from clinical jobs and from committed prescription collections.
Supplement provenance does not imply physician review. A fresh explicit user review
is required before handing candidates to the existing quick-analysis screen; that
screen keeps its original review/preview rules. Clinical archival and prescription
commit remain in their original interfaces. Public knowledge receives no patient
text, task text or draft automatically. Knowledge-source selection transfers only
the chosen public source identifier.

## Interface

Add `#assistant` and a persistent navigation entry. Show task instruction/selection,
plan, intake text, missing-field cards, provenance controls, draft save/resume,
categorized source cards and saved-case search. Keep unsaved state in memory across
navigation, warn on closing with edits, and clear all sensitive in-memory state on
logout. Bind asynchronous results to session and input revisions. Preserve original
iframe identity, nested navigation and downloads.

## Implementation and acceptance

1. Add one backend module for bounded task operations and account-scoped draft store.
2. Add one frontend module and focused host navigation/style wiring.
3. Add source selection and reviewed-candidate handoff to the existing domain UI.
4. Verify unknown/multi-intent requests, missing/unavailable observations, stale and
   duplicate writes, account isolation, raw-source provenance, logout/request races,
   empty knowledge categories and saved-case search. Use synthetic inputs only.
5. Run portable suites and integration smoke. Verify desktop/tablet/mobile rendering,
   keyboard navigation, reload/resume and unchanged prescription iframe/downloads.

The deliverable is an isolated local synthetic preview and reproducible source.
Candidate graph retrieval, general semantic search, new databases and patient-facing
consultation remain experimental options requiring separate evidence of value.
No model-quality, clinical-accuracy or medical-release claim follows from software
tests. No new Git publication or private-service replacement is part of this change.

## Source-informed extension

The user subsequently supplied the upstream archive and authorized implementation
after source review. See `Source-Informed-Assistant-Plan.md` for the additive history
routes, guided supplementation and cancellable read-only operation states. The draft
schema, original module boundaries and explicit save/review contract remain unchanged.
