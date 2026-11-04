# Expert collaboration in Knowledge Q&A

Choose Herb or Formula consultation, then **Expert collaboration** as the
processing method. Enter a named subject and a public educational question;
select a disease/source scope if needed. The existing single-model and literature
modes remain available.

## What actually runs

A compiled LangGraph StateGraph retrieves local passages and executes four
role calls:

1. TCM knowledge: identity, processing/version distinctions and traditional theory.
2. Literature evidence: what the supplied passages actually describe.
3. Pharmacy review: cautions, missing information and concerns about prior claims.
4. Synthesis: a concise overview and a selection of existing claim IDs.

The first two roles do not receive one another's opinions. TCM receives the name
and kind for a general reference entry; the evidence role receives the question
and retrieved passages. Pharmacy sees their
validated outputs; synthesis sees all validated reports. The default local mode
runs sequentially to avoid competing GPU requests. Selecting **Local + Kimi API**
runs the Kimi TCM role concurrently with local evidence, then uses the local model
for pharmacy and synthesis. Kimi receives the kind, name and acknowledged current
public question only. Local passages, source metadata and role reports remain
local. Each hybrid job makes at most one Kimi call. Model agreement is not
independent expert confirmation. There is no
free-running debate, autonomous prescribing or arbitrary tool execution.

**All Kimi 3.1** runs all four roles with `kimi-k3.1-pro`, without local model
inference. TCM and evidence run concurrently, followed by pharmacy and synthesis.
This mode requires separate consent to send selected public literature excerpts
and derived role reports. At most three complete passages totaling 2,600
characters are sent; sources without public PMID/DOI identity or with obvious
identity markers are omitted. Source files, paths, full records, whole-library
content and patient data are excluded. Pharmacy sees selected excerpts and prior
validated reports; synthesis sees report fields without duplicate quotations.
This makes at most four API calls per job. Local retrieval and exact quotation
attachment remain server operations. Review the visible transmitted scope and
original passages before accepting any interpretation.

The local collaboration budget is 8,192 context tokens, 768 generated tokens per role,
and 2,600 characters of complete retrieved passages. Oversize passages are omitted,
not truncated, and the UI reports omissions. These limits are specific to the
collaboration path; the original literature and single-model paths are unchanged.
Local JSON mode includes the output schema in the prompt; strict server schema,
quotation and claim-reference validation still decides what can be displayed.
The Kimi role uses the existing bounded JSON API transport with a 4,096-token
response budget, including reasoning where applicable. K3 uses low reasoning
effort; reasoning content is discarded. Both paths enforce the same TCM schema.

The server labels TCM points and pharmacy risks as model knowledge. The evidence
role must select a known passage containing the named subject for every claim.
The server attaches that complete original passage as a quotation; models do not
rewrite quotation text. Source identity does not establish semantic support,
medical accuracy or completeness. Read the linked original before accepting an
interpretation. The rheumatology collection is not a comprehensive materia medica
or interaction database; missing warnings never establish safety.

## Results, review and stopping

The interface polls actual role states. A failed role produces a visible partial
result, not a simulated answer or automatic retry. A model transport failure skips
remaining calls to that provider rather than repeating the same unavailable operation.
A Kimi failure leaves the local evidence, review and synthesis available, with a
visible partial result and sanitized error. Role receipts identify configured and
reported models, input scope and timing. Pharmacy concerns appear
separately and survive synthesis failure. Insufficient evidence is also visible.
If source integrity changes, generated content is withheld.

Stopping requests cooperative cancellation: the active model call can finish,
but subsequent roles are skipped. Editing the question/scope or leaving the view
discards stale UI responses. A disconnected browser cannot guarantee cancellation
of work already accepted by the server. The server serializes all knowledge model
requests; another request receives `busy` while a collaboration is running.

Review is explicit. Checking the review box records a user acknowledgment in the
downloaded JSON; it does not change clinical approval or archive a patient record.
Downloads contain the question, validated result, model-call receipts, workflow
and prompt versions, request/index/result hashes and review timestamp. Keep local
outputs outside a public Git repository.

Jobs and results are account-scoped memory only: up to 16 finished results,
30-minute expiration, lost on service restart. The browser's current result stays
until its page/session state is cleared. Use the explicit download to keep a
report. This is not database-backed report history or LangGraph checkpoint resume.

## Configuration and API

The existing local and Kimi model configuration is reused. Hybrid mode requires a
configured Kimi key and explicit public-topic acknowledgment. DeepSeek remains a
single-model option. Mixed mode keeps passages and reports local. All-Kimi sends
selected public excerpts and derived reports only after its separate consent gate.
Synthetic-demo mode does not run medical inference.

- `POST /api/department/knowledge/collaborate`: same strict request as consultation,
  with `provider=local` or `provider=kimi` (hybrid, requiring
  `public_topic_confirmed=true`); returns an opaque job ID or an unavailable/busy status.
  All-Kimi additionally requires `expert_mode=all_kimi` and
  `public_evidence_confirmed=true`. These fields apply only to expert jobs.
- `GET /api/department/knowledge/collaborations/{id}`: authenticated owner-only progress
  and result; expired/unknown/cross-account IDs return 404.
- `POST /api/department/knowledge/collaborations/{id}/cancel`: body `{}`.

See [the v3 all-Kimi contract](All-Kimi-Expert-Tech-Spec.md),
[the v2 hybrid contract](Hybrid-Expert-Tech-Spec.md),
[the original local contract](Expert-Collaboration-Tech-Spec.md),
[verification results](Expert-Collaboration-Verification.md) and
[model configuration](Model-Configuration.md). Later dynamic intake and local case
discussion are separate stages; the existing intake graph still performs source
collection and explicit human review.
