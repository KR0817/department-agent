# Local and Kimi expert collaboration

Date: 2026-11-05

## Scope and acceptance

Extend the existing herb/formula expert mode with an explicit local + Kimi
selection. Keep local-only as the default, all existing modes, original library,
run data and prescription views. Reuse the bounded official API transport and
the four role schemas. No new dependencies, corpus transfers or publication.

In hybrid mode the TCM reference role uses Kimi while the local evidence role
runs concurrently. Local pharmacy and synthesis then consume validated reports.
Kimi receives only kind, subject and the current acknowledged public question,
plus a fixed role prompt/schema. Local passages, source metadata, role reports,
patient records and prior conversation are excluded from the remote request.
One external call per job, no automatic retry/fallback. Model agreement is not
clinical validation. Source identity and human-review requirements remain intact.

## API and orchestration

The existing strict consultation request and authenticated job routes remain.
`provider=local` retains sequential local execution; `provider=kimi` selects
hybrid execution and requires `public_topic_confirmed=true`. Reject DeepSeek for
expert jobs. Validate public input and Kimi configuration before starting work.
Catalog collaboration metadata lists supported providers and workflow v2.

LangGraph v2 routes local jobs through the original four sequential role nodes.
Hybrid jobs use a bounded two-worker parallel reference node, join both results,
then run local pharmacy, synthesis and source verification. The node uses the
standard library executor rather than introducing another scheduler. Each worker
disables tracing explicitly. Publish role status under a lock. Provider-specific
transport failures skip only later calls to that provider. Cancellation or a
source integrity failure prevents downstream calls and withholds all content.
In-flight HTTP/model calls cannot be recalled; stopping prevents later work.

Results and polling include role provider/model metadata. Call receipts record
provider, configured and reported model, sent scope, start offset, duration and
stable sanitized error codes. Retain existing bounded ephemeral job ownership,
shared cross-mode lock, schema validation, source hashes and manual downloads.

## UI

Add an expert-model selector distinct from the single-model choice. Require
public-topic acknowledgment for hybrid mode and show missing configuration.
Explain role allocation and remote input scope before submission. Show actual
models in progress and results. Input/provider/scope/view/session changes cancel
waiting, invalidate late results and reset result review acknowledgment as before.

## Verification and deployment

Test actual overlapping reference calls and downstream join, remote input
allowlisting, missing acknowledgment/key, provider failures, tracing, cancellation,
source changes, owner/auth/origin boundaries and old local behavior. Run relevant
backend and frontend suites, source-boundary scan, desktop/tablet/mobile checks.
Use only synthetic fixtures in automated tests. Real hybrid validation uses a
public topic, preserves the original library and reports observed role outcomes.
Current credentials are process-only; do not extract them from the old service.
Prepare and verify changes before any necessary masked local restart input.
