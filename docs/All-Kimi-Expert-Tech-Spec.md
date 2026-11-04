# All-Kimi expert mode

Date: 2026-11-05

The user explicitly authorized sending selected public literature passages and
reports derived from those public materials to Kimi, excluding patient records,
private cases and whole-library exports. Extend v2 without changing its defaults.

## Contract and acceptance

Expert requests add `expert_mode=all_kimi` and
`public_evidence_confirmed=true` to `provider=kimi` and the existing
`public_topic_confirmed=true`. These fields are accepted only by the expert
endpoint; single consultation keeps its original strict contract. Catalog lists
supported execution modes. Missing acknowledgment, configuration or the requested
`kimi-k3.1-pro` model must block dispatch. Local-only and mixed modes remain.

All four roles use Kimi 3.1. Reference and evidence roles run concurrently, then
pharmacy and synthesis follow their validated outputs. Maximum four calls, no
automatic retry or fallback. All-Kimi does not require a running local model.
Local source retrieval, integrity verification, quote attachment and human review
remain server operations. Provider/model, transmitted scope and passage counts
are recorded per call. Agreement between roles sharing Kimi is not independent
confirmation of clinical correctness.

Public excerpt selection remains bounded to three complete passages totaling
2,600 characters; omit rather than truncate. Only sources carrying a public
PMID/DOI identity are eligible for external passage analysis, and obvious identity
markers block external dispatch. Report omissions explicitly. No uploads, saved
drafts, patient records, local file paths, full source records or whole indexes
enter API payloads. TCM sees only public input. Evidence sees selected ID/text
pairs. Pharmacy sees those pairs and validated prior claims. Synthesis sees
validated reports only. Strip duplicate quotations and unrelated metadata from
forwarded reports, preserving IDs, findings, uncertainty and review concerns.
The fixed HTTPS transport allowlists these fields and requires explicit consent.

## UI and verification

Add All Kimi 3.1 to the expert-model selector, with a separate public-literature
consent checkbox and a clear four-call/input-scope note. Changing the model clears
consent and stale results. Result/progress labels identify all four Kimi roles.
Keep API errors, insufficient evidence, partial results and manual source review.

Verify all four real graph roles use the API, no local inference occurs, privacy
allowlists and consent gates hold, report dependencies join correctly, provider
failures stop downstream requests, and old modes still pass. Run relevant full
backend/state suites and desktop/mobile browser checks. A live public-topic job
must report four Kimi 3.1 calls and unchanged library hashes. Keep operational
receipts outside Git. No source publication is requested.
