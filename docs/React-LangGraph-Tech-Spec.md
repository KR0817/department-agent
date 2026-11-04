# React consultation and LangGraph workflow

Date: 2026-11-02
Status: implementation contract

## Outcome and scope

Add a working React/TypeScript consultation workspace at `/#consultation` to the
existing FastAPI host. Preserve the original assistant, clinical review, knowledge
and complete prescription pages. React owns the new page; frontend source and
build tooling live independently in `frontend/`. Production assets are served on
the same origin, using the existing session and CSRF boundary. Node is a build
dependency, not a second production service.

Use an actual compiled LangGraph StateGraph for each consultation turn:
`START -> recognize -> assess -> ask_question | request_source | review -> END`.
The review branch distinguishes readiness from an explicit human confirmation.
Questions ask for source observations; they do not generate diagnoses or drugs.
The six existing intake fields and parser remain authoritative. This workflow is
deterministic and local, with no LLM call or external tracing.

## API contract

`POST /api/department/assistant/consultation`

Request: `{ "action": "advance" | "review", "draft": DepartmentTaskV1 }`.
`DepartmentTaskV1` is the existing validated assistant draft, with `task=intake`.
Unknown keys, invalid observations, empty recorded values and stale record IDs
are rejected. Authentication, origin checks and the existing payload size limit
apply. Review with unresolved fields or no recognized records returns 409.

Response:

- `engine`: `langgraph`; `model_called`: false.
- `stage`: `need_source`, `question`, `review_ready` or `reviewed`.
- `trace`: executed node names, collected by the graph itself.
- `question`: null or `{record_id, field, prompt}`.
- `counts`: `{pending, recorded, unavailable}` for supplemental observations.
- `prepared`: existing prepare response, retaining original records, hashes,
  evidence and explicit supplemental observations.
- `clinical_approval`: null. Explicit review permits only handoff to the existing
  quick-analysis review; original business archival remains a separate action.

Existing draft/list/history APIs remain the persistence contract. Explicit saves
append revisions with optimistic conflict checks and retry idempotency. Each
turn reconstructs graph state from the source and observations; there is no
second checkpoint store, LangGraph interrupt claim or silent autosave. Reopening
a saved draft reruns the same graph to resume the next question.

## Frontend behavior

Provide source entry, synthetic example, data-origin declaration, a next-question
card, source/status selection, unavailable response, completed observation list,
review summary and explicit handoff. Allow correction of observations and reset
review whenever input changes. Show actual graph steps and operation states.

Reuse the existing account-scoped draft list and version history. Preview and
restore previous content into a new revision. Do not overwrite dirty state when
opening another task. Retain unsaved edits while navigating the host, warn on
browser close, discard stale responses and abort owned reads on navigation/logout.
Saving is not cancellable; reconcile its revision even if the page is inactive.
Logout clears all in-memory consultation state. No localStorage or URL contains
clinical text. Public knowledge links do not carry case text.

## Build and delivery

Pin React, TypeScript, Vite and LangGraph versions in npm/uv lock files. Build local
JS/CSS under ignored `clinical/static/consultation/`; do not load CDN scripts or
weaken CSP. `npm --prefix frontend ci` and `npm --prefix frontend run build` must
reproduce the frontend. CI builds before synthetic tests. Add React/LangGraph
license notices and document the incremental frontend scope accurately.

## Acceptance and verification

1. Typecheck and build the React source; exercise real components in DOM tests.
2. Test actual graph branches, multi-turn answers, original-source preservation,
   empty/invalid inputs, stale IDs and premature review rejection.
3. Verify session/origin protection and persistence isolation through HTTP tests.
4. Exercise restart and all original modules with the isolated smoke test.
5. Run existing Python and JavaScript suites and public-source boundary checks.
6. Verify the built UI at desktop and mobile sizes: complete a synthetic turn,
   save/reopen, preview/restore history, cancel waiting, review/handoff, navigation,
   logout and absence of console errors or overflow.

Only source and synthetic fixtures are in scope. Private deployments, existing
services and published v0.2.0 remain unchanged. Publication is a separate step.

## References

- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://react.dev/learn/build-a-react-app-from-scratch
- https://vite.dev/guide/backend-integration
