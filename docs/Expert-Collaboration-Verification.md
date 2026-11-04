# Expert collaboration verification

Date: 2026-11-03

This is the historical local-only verification record. The v2 implementation
and its checks are documented in [hybrid verification](Hybrid-Expert-Verification.md).

## Scope

This iteration implements bounded local herb/formula collaboration in Knowledge
Q&A. The TCM, literature and pharmacy roles make separate calls, followed by a
synthesis call, through a compiled LangGraph StateGraph. All roles currently use
the same local model. Tests of routing and source identity do not establish
clinical accuracy, independent expert agreement or superiority to a single call.

## Automated verification

- Most recent module suite results: clinical 365 passed; knowledge 157 discovered,
  133 passed and 24 explicitly skipped because private frozen-corpus fixtures are
  absent from the public checkout; prescription 262 passed; release/lifecycle 17
  passed. The clinical suite was rerun after the final source-binding change.
- Focused backend suite: 36 tests passed, including 17 collaboration tests plus
  the existing consultation and knowledge tests. Fixtures are synthetic and model
  transports are mocked; graph execution itself uses the installed LangGraph.
- Browser state suites: 19 tests passed across the assistant and knowledge UI.
  Coverage includes stale results, account/logout boundaries, polling failures,
  cooperative cancellation, explicit review and preservation of earlier modes.
- Integrated synthetic HTTP smoke: 170 checks passed, including the clinical
  workflow, original literature endpoints, all 14 prescription assets and five
  prescription/analysis views, consultation graph and persistence/restart.
- Browser layout/interaction verification: 44 checks passed at widths 1440, 768
  and 390. Role completions were synthetic intercepted responses, while the catalog
  came from the connected local library. These checks cover progress, partial
  results, concerns, download/review, cancellation, original modes, text safety,
  full-passage expansion without changing original text, overflow, page errors
  and browser network destinations.

Local receipts and screenshots are in ignored
`work/expert-collaboration-20261103/`. No runtime outputs, literature or private
configuration are part of the source distribution.

## Real-model findings and changes

Development probes used only public herb/formula names and educational questions
with the existing local qwen3:14b runtime. No patient context or external API was
used. Failed attempts are retained locally, rather than counted as successful.

Initial prompts produced insufficient outputs, invented quotation fields and
occasionally transport failures. The server rejected invalid responses. The
implementation now separates role output schemas, assigns provenance server-side,
uses a smaller bounded context and stops subsequent calls on transport failure.

An evidence-role diagnostic attempted to attribute a multi-herb formula's effects
to one component herb and rewrote source whitespace. Its quotation failed exact
source matching. The final contract instead lets the model select known passage
IDs and attaches their complete original text server-side. Model-generated quote
fields are rejected. Selected passages must contain the named subject, and role
instructions distinguish formula findings from component-herb effects. This
is a limited software constraint, not a semantic-support proof. Unverified model
knowledge remains visibly separate from quoted material.

Pharmacy has a dedicated risk schema and reviews known claim IDs; it must not
merely repeat botanical identity or traditional functions. Concerns remain visible
independently of the summary. A comprehensive interaction database and a clinician-
reviewed evaluation set remain outside this iteration.

The final public-topic probes completed all four calls: the herb example took
233.812 seconds and the formula example 93.866 seconds on the tested machine.
The formula retrieval explicitly returned no matching passages and the evidence
role reported insufficient evidence. The unchanged single-model herb path had
previously returned an answer in 100.123 seconds; that receipt was reused, not
presented as a newly repeated call or a comparative accuracy benchmark.

**Clinical content acceptance is not passed.** Manual inspection of the final
herb probe still found incorrect formula-component and efficacy attribution. The
pharmacy role raised general limitations but did not fully correct those errors.
The source text itself remained intact. The feature is therefore labeled as a
local trial and requires source-by-source human review. Successful graph status
means execution and schema validation completed, not that its interpretations are
correct. A clinician-labeled claim-support test set is the next acceptance gate.

## Operational boundaries

Expert collaboration is local only. DeepSeek/Kimi remain separate options in
single-model consultation; this iteration does not validate their credentials.
Jobs live in account-scoped process memory, expire after 30 minutes once finished,
and do not resume after a restart. Explicit JSON download is the persistence path.
Cancellation stops later roles; an already running model call may finish.

The local workbench was updated on its existing port and run/data directory.
Its library still has 230 records, 229 full texts, 228 retrieval-eligible sources
and 5,801 chunks. Five original catalog/index/manifest hashes are unchanged. A
real request through the original literature mode returned three source-bound
extracts with Chinese text and original-reader links in 42.618 seconds. The
collaboration catalog/guard and provider-configuration flags were checked on the
updated service. The separate staging host was stopped; the current workbench
and original local model remain running.

The actual workbench entry was opened and visually checked in the in-app browser;
`live-workbench.png` shows the trial selector and review warning, not a fabricated
inference result. The original source reader remains available. Global memory and
the public Git release were not changed.
