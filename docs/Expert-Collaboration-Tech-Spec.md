# Source-bound expert collaboration

Date: 2026-11-03

Historical v1 contract. The [v2 extension](Hybrid-Expert-Tech-Spec.md) adds an
explicit local + Kimi path while retaining the local behavior described below.

## Scope and acceptance

Implement the first approved stage inside Knowledge Q&A: named herb/formula
questions processed by TCM knowledge, literature evidence, pharmacy review and
synthesis roles. Preserve single-model consultation, original literature Q&A,
React intake, clinical review and every prescription view. Later dynamic intake
and case discussion are separate stages requiring their own validation.

Use the existing local model and actual LangGraph StateGraph. TCM receives only
the name/kind for its general-reference subtask; evidence receives the original
question and frozen passages. Pharmacy reviews their validated
claims; synthesis selects those claims and retains review concerns. Execute
roles sequentially to respect the current local GPU/model lock. This is bounded
role collaboration, not independent clinicians, unrestricted tools or a diagnostic
system. No new model downloads, cloud calls, dependencies or Git publication.

Acceptance: real role-specific calls and graph traces; authenticated live
progress; exact quotation/source binding; visible insufficient/partial/failed
states; preserved concerns; cooperative cancellation; immutable version metadata;
manual result download and review state; desktop/mobile operation; real local
model probe plus original literature regression and source preservation.

## API contract

- Catalog adds `collaboration` availability, local provider and workflow version.
- `POST /api/department/knowledge/collaborate` accepts the existing strict
  ConsultationInput contract, with provider restricted to local. Validate source
  scope/index and public question before reserving the shared model lock.
  Success returns an account-owned opaque job ID, status, stage and role states.
  Synthetic mode, busy and invalid requests never dispatch a model.
- `GET /api/department/knowledge/collaborations/{id}` returns only the owning
  account's progress/result. Other accounts and invalid IDs receive 404.
- `POST /api/department/knowledge/collaborations/{id}/cancel` accepts `{}` and
  requests cancellation. A current model call may finish; later roles are skipped
  and the cancelled result is not displayed as completed.

Jobs are bounded in-memory state, expire after 30 minutes once finished, and are
lost on service restart. Keep at most 16 completed results plus the active job.
No question/report logging or automatic database persistence. A user can explicitly
download a result with workflow, prompt, request and source versions. It is not a
LangGraph checkpointer or a clinical archival action.

## Graph and output contract

`retrieve -> tcm -> evidence -> pharmacy -> synthesize -> verify -> END`, with
cancel/fatal-source checks before role calls. Each stage publishes its actual
state; graph execution disables external tracing. Maximum four model calls, no
automatic retries or debate loop. Transport failure skips remaining calls rather
than repeatedly waiting on an unavailable model. A failed role is visible; surviving validated
reports may be returned as partial, and synthesis cannot hide a failed stage.

Each role returns a strict schema: TCM returns bounded points and uncertainties,
evidence returns findings referencing passage IDs, and pharmacy returns risks, uncertainties
and review concerns. The server derives availability and model-knowledge versus source
basis instead of asking a general role to fill empty citation fields. Source claims
must select a known passage ID. The server attaches the complete frozen passage
as the quotation; models cannot rewrite quotation text. That passage must contain
the named subject (ignoring whitespace only for this name check). The evidence role
cannot emit unsourced claims. These checks verify quote identity, not clinical
truth or semantic entailment; retain a human-support-review label. Server-generated
claim IDs are the only IDs later roles/synthesis can reference. Pharmacy concerns
remain visible independently of synthesis. The source corpus is not a complete
drug-interaction database; no negative screen is a safety clearance.

Synthesis selects existing claims, provides a concise overview and unresolved
issues. Validate IDs and retain original claim provenance. Reject dose
instructions, generated bibliography, unknown references, tool calls, malformed
or truncated JSON. Source integrity is checked before and after inference;
changed sources invalidate generated content. No patient-specific prescribing.

Runtime tuning: use an 8,192-token context, 768-token output cap and 2,600-character
complete-passage budget. Preserve omitted-passage counts. Use local JSON mode with
the schema in the prompt and strict server-side validation; do not repair malformed
model outputs. Record generation budget with the prompt/schema digest.

## Frontend

Add a single-model/expert-collaboration selector to herb/formula modes. Expert
mode explicitly uses the local model and shows stage statuses, role reports,
selected conclusions, source quotations and preserved concerns. Poll via the
existing authenticated same-origin client. Cancel polling and discard stale
responses on input/mode/source/view/session changes. Explicit stopping also
requests cooperative server cancellation when the job ID is known.

Manual review records only that the user has checked the displayed result; it
does not grant clinical approval. A downloaded JSON includes this distinction and
the exact result identity. No clinical source content is carried into questions.

## Verification

Use synthetic tests for actual graph routing, independent role inputs, downstream
claim visibility, quote/ID validation, partial failure, cancellation, bounded jobs,
cross-account access, auth/origin, disabled tracing and source-change rejection.
Exercise JS stale/poll/cancel/review states and desktop/mobile rendering with
synthetic completions. Run actual local collaboration and single-model comparison
on public topics; report latency and observed citation behavior without claiming
medical superiority. Verify the original library identity and original Q&A on the
final local workbench. Preserve prior edits and local data on controlled restart.

References: https://docs.langchain.com/oss/python/langgraph/graph-api and
https://docs.langchain.com/oss/python/langgraph/workflows-agents.
