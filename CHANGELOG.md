# Changelog

## 0.3.0 - 2026-11-05

- Add a separate React/TypeScript consultation workspace with versioned draft recovery.
- Execute source parsing, missing-field questions and explicit review through LangGraph.
- Preserve original clinical, knowledge, prescription and assistant workspaces.
- Build local frontend assets with Vite; retain same-origin authentication and disable external graph tracing.
- Add structured herb/formula consultation with local, DeepSeek and Kimi transports.
- Add four-role expert collaboration with progress, cancellation, source identity and manual review.
- Support local-only, local + Kimi and all Kimi 3.1 modes, with explicit public-evidence consent for all-Kimi.
- Preserve the connected local literature index while excluding its corpus from the public release.

## 0.2.0 - 2026-11-02

- Add a department assistant for explicit task selection, intake supplementation,
  public knowledge source selection and lexical search of committed case records.
- Guide missing information one field at a time, preserve observation origins and
  distinguish unasked, recorded and unavailable fields before manual review.
- Save account-scoped task drafts with append-only revisions, conflict protection,
  idempotent retries, paginated history and explicit version recovery.
- Show operation status and cancel browser waiting without accepting late results.
- Preserve clinical archival, source-bound evidence checks and the full MingYiRx
  workspace, including all 14 original generated resources.
- Add assistant backend, frontend-state and integration coverage. No new runtime
  dependency, upstream source transplant, React or LangGraph integration is included.

## 0.1.1 - 2026-10-29

- Refine navigation, responsive layout, clinical source reading and the full
  prescription workspace while preserving original review and persistence flows.

## 0.1.0

- Publish the integrated clinical, knowledge and prescription source distribution
  with explicitly synthetic demonstrations and local-only defaults.
