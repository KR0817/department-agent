# Source-informed assistant improvements

Date: 2026-11-02

## Evidence and scope

Review input: user-supplied `agent-chinese-med.zip`, SHA-256
`17ca1d709bdf2a2c693913ba8d3eb2b406f6ed9f1d9dd6c3ae5fced86544f328`.
The archive contains 1,707 entries. Selected application source is inspected
separately from this distribution; upstream setup and model calls are not run.
Remote repository identity and runtime performance remain unverified.

The actual chat service imports `agent.tcm_service`, rather than the parallel
`final_agent` tree. The active graph has structured information collection,
interrupt/resume and UI event types. References relative to the supplied archive:

| Source | Observed behavior | Decision |
| --- | --- | --- |
| `backend/app/src/service/chat_servcie.py:21` | Imports the active TCM service | Follow its call path, not similarly named experiments |
| `backend/app/src/agent/components/diagnose/nodes/collect_info.py` | Structured observation collection with history | Keep explicit fields and provenance; add one-at-a-time supplementation |
| `backend/app/src/agent/components/diagnose/nodes/analyze_follow_up.py:174` | Interrupts to collect a response | Resume from unresolved fields in a saved draft; no new graph runtime |
| `backend/app/src/agent/tcm_service.py:201` | Thread, state, interruption, content and error events | Show actual request states, distinguish cancellation and failure |
| `backend/app/src/agent/checkpointer.py:78` | Storage failure can fall back to memory | Preserve durable SQLite revisions; surface failures |
| `backend/app/src/agent/components/diagnose/nodes/complex/tools/vector_tools.py:83` | Retrieval failure returns simulated cases | Keep errors and empty results explicit; never fabricate evidence |
| `backend/app/src/agent/components/diagnose/nodes/complex/tools/web_tools.py:147` | Literature failure returns simulated papers | Do not import this fallback |
| `frontend/src/views/Public/PublicPortal.tsx:1100` | Routes stream state to session UI | Bind responses to the current task/view and retain abort guards |

`backend/README.md:265` states MIT, but the archive has no application-level
license text or copyright notice; the only LICENSE file belongs to the vendored
GraphRAG project. Adopt interaction and architecture ideas through independent
implementation. Do not copy upstream code, prompts, assets or medical corpora.

Official [interrupt documentation](https://docs.langchain.com/oss/python/langgraph/interrupts)
explains that resumed nodes restart from their beginning. The
[persistence documentation](https://docs.langchain.com/oss/python/langgraph/persistence)
distinguishes thread checkpoints from cross-thread stores. Any future graph adapter
must preserve idempotent business writes and account ownership; these documents are
not evidence that the supplied archive has been executed successfully.

## Deliverable and API contract

1. **Guided supplementation.** The existing six-field schema remains unchanged.
   Display one unresolved field at a time with patient/visit context, an explicit
   recorded/unavailable choice and information origin. Keep all-fields editing.
   Progress counts recorded, unavailable and still-unasked fields separately;
   it is not a clinical sufficiency score. Answers update the local draft, then
   reuse `/prepare`; explicit save persists them. Resume derives pending fields
   from the saved draft. Recheck before clinical handoff.
2. **Revision inspection and recovery.** Add authenticated read-only routes:
   `GET /drafts/{id}/history?before=N` returns up to 20 revision summaries,
   newest first, with `next_before`; `GET /drafts/{id}/revisions/{revision}`
   returns one immutable version. A missing account-owned draft/version is 404;
   invalid positive cursor/revision is 422. Both inherit host no-store policy.
   Preview a selected version; explicitly load its contents into the current
   draft, retain the current optimistic revision, then save a new revision.
   Unsaved edits block replacement. Concurrent changes still return 409.
3. **Operation feedback.** Planning, recognition and case search show real local
   request running/completed/failed/cancelled states. Cancel aborts the browser
   request and discards late results, not a promise that the server stopped.
   Saves are not cancellable: a lost acknowledgement is handled by existing
   idempotency. No fake model thought process, time estimate or SSE dependency.

No data migration or new dependency. Existing v1 drafts, legacy context defaults,
human review, public-source separation, full prescription iframe and all 14
resources remain compatible. This is a local synthetic preview and source change.

## Acceptance checks

- Missing fields advance without inventing values; unavailable stays distinct.
- Blank recorded answers are rejected. Source edits invalidate prepared results.
- Saved drafts resume pending fields and retain original evidence hashes.
- Revision history is bounded, paginated and account-isolated; recovery appends,
  preserves history, and retains optimistic conflict protection.
- Cancellation ignores even a late successful response; editing and logout races
  retain existing protections. State describes requests, not clinical decisions.
- Run focused backend/frontend tests, integration smoke, syntax/diff checks,
  desktop and mobile browser workflows. Preserve prescription asset coverage.
- Record actual results and limitations in a verification document and update
  project MEMORY. Do not modify global memory or private running services.
