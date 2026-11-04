# Department Agent project overview

Version: 0.3.0
Date: 2026-11-05

Department Agent brings clinical document review, departmental knowledge and
MingYiRx prescription analysis into one authenticated workbench. It serves a
clinician or researcher who needs to move from original records to reviewed
observations, traceable literature answers and longitudinal prescription views.
The interface is simplified Chinese. The public installation uses synthetic data;
real literature, clinical datasets and model credentials are supplied separately.

## Workspaces

| Workspace | Main operation | Output and persistence |
|---|---|---|
| Clinical review | Upload supported documents, inspect source locations and review candidate fields | Versioned archival, corrections and recoverable partial publication |
| Patient overview | Navigate patients, visits, observations and follow-up tasks | Source-bound longitudinal records; locally queued follow-up messages |
| Department assistant | Select a task, supplement missing information and search saved cases | Account-scoped append-only drafts and revision recovery |
| Guided consultation | Use a React form to collect source records and missing observations | LangGraph decisions, explicit review and handoff to visit analysis |
| Knowledge Q&A | Scope literature, read source-bound extracts, consult about herbs/formulas | Original quotations, model knowledge labels and source links |
| Expert collaboration | Run TCM, evidence, pharmacy and synthesis roles | Live progress, partial-failure status, manual review and JSON download |
| Prescription analysis | Open the complete MingYiRx workspace or quick visit comparison | Aggregate, exact-prescription, inheritance and reviewed collection views |

The clinical and prescription modules retain their own identity and persistence
semantics. Opening them in one session does not automatically merge records or
authorize an archive operation. Every handoff keeps its original review step.

## Source review and guided intake

Clinical candidates remain connected to their source text or document location.
The operator can accept, modify, reject or defer a candidate before archival.
Corrections and partial-write recovery preserve the existing record history.
The declared schema contains 19 field types; actual extraction accuracy depends
on the configured input and extraction path. The default demonstration uses
explicitly marked synthetic CSV records and a synthetic FHIR service.

The assistant and React intake share an account-scoped versioned draft store.
Missing observations can be answered or marked unavailable. Restoring a historical
draft loads a preview; saving appends a new revision against the current version.
The intake LangGraph routes parsing, missing-field assessment and human review.
Those intake decisions are deterministic. The separate knowledge expert graph
performs model inference. There is no second graph checkpoint database.

## Literature and model consultation

Original literature Q&A selects source-bound extracts and preserves source links,
translation labels and index identity. Herb/formula consultation adds structured
identity, traditional rationale, research context, cautions and uncertainty.
Models can use general knowledge, while quotations and research support keep
separate provenance. Literal subject matching can miss synonyms or translations.

The original local collection has been connected and tested, but its papers,
translations, indexes and model weights are excluded from this source release.
The repository distributes the adapter and synthetic fixtures. Users connect an
authorized corpus through `--knowledge-mode fulltext --knowledge-root ...`.

## Expert modes

| Mode | TCM knowledge | Evidence | Pharmacy and synthesis | External input |
|---|---|---|---|---|
| Local | Local model | Local model | Local model | None |
| Local + Kimi | Kimi | Local model | Local model | Acknowledged public question and named subject |
| All Kimi 3.1 | Kimi 3.1 | Kimi 3.1 | Kimi 3.1 | Acknowledged public question, selected public excerpts and validated reports |

In mixed and all-Kimi modes the first two roles run concurrently, then pharmacy
reviews their validated outputs and synthesis selects existing claim IDs. The
server attaches exact original passages; it does not accept generated quotations.
Source identity does not establish semantic support. Pharmacy concerns remain
visible even if synthesis fails, and role agreement is not independent validation.

All-Kimi requires `kimi-k3.1-pro` and separate public-evidence consent. It makes at
most four API calls and does not require local model inference. External excerpts
are capped at three complete passages totaling 2,600 characters. Public PMID/DOI
metadata and identity-marker checks bound eligible excerpts. Local paths, patient
records, saved drafts and whole-library exports are excluded. No automatic retry
or provider fallback is performed. The shared job lock serializes knowledge jobs.

Job results stay in owner-scoped process memory with bounded retention. Download
a result explicitly to retain it. Cancellation prevents later work and discards
stale UI results; an in-flight API call can still finish and be billed. Review
acknowledgment does not grant clinical approval.

## Complete prescription analysis

The workbench retains the original MingYiRx iframe and its 14 generated resources.
The user can open aggregate analysis, exact-prescription comparison, inheritance
views, import/review tools and report downloads. Expanded canvas mode preserves
the same iframe state. Reviewed imported collections use revisioned storage;
inheritance annotations retain their separate draft/export workflow.

Quick visit comparison recognizes patient/episode identifiers and visit order,
then compares additions, removals, retained herbs and dose changes where the units
and order are interpretable. Ambiguous same-day ordering remains unresolved.
These are descriptive comparisons; treatment attribution and efficacy require
separate study designs and clinical review.

## Architecture and deployment

FastAPI owns authentication, JSON routes and workflow adapters. React/TypeScript
currently implements the guided consultation page; the existing business pages
retain their vanilla JavaScript implementation. Vite produces local assets, and
the deployed application serves them from the same Python host. Frontend/backend
separation is at the source and API boundary; separate production hosts are not
required. Node is used for building and testing, not as a production app server.

LangGraph is used for intake decisions and bounded expert orchestration. SQLite
stores existing account-scoped drafts and local application state. Clinical FHIR
integration has its own configured pathway; the public demo starts synthetic FHIR.
External model keys stay in server process configuration and are never placed in
the browser. The release retains locked Python/npm dependencies and third-party
notices, with the integrated source licensed AGPL-3.0-only.

Start from a Git clone, run `uv sync --frozen`, install frontend dependencies with
`npm --prefix frontend ci --ignore-scripts`, build with
`npm --prefix frontend run build`, then use `uv run --frozen python scripts/start.py`.
The default workbench is `http://127.0.0.1:18894/`. The synthetic demo needs no model
key or GPU. Optional real-model paths require their own validated environment.

## Verification and current limits

Source tests, frontend state checks, browser layouts and isolated HTTP smoke
cover the software workflows. Live local/hybrid/all-Kimi probes are described in
the versioned verification documents. The all-Kimi example completed four Kimi 3.1
calls in 64.789 seconds on the tested deployment; this is one measured example,
not a latency guarantee or clinical benchmark. DeepSeek transport is implemented
and tested with mocks, while real-account readiness remains unverified.

The current library is not a comprehensive materia medica or interaction database.
Intake, extraction and model-generated interpretations still require professional
review. Formal extraction/clinical-accuracy benchmarks, broader validated domain
coverage and institution-specific production operations remain future work.

See [release notes](Release-v0.3.0.md), [model setup](Model-Configuration.md),
[expert usage](Expert-Collaboration.md) and [all-Kimi verification](All-Kimi-Expert-Verification.md).
