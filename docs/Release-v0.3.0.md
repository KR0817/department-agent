# Department Agent 0.3.0

Date: 2026-11-05

## Release scope and acceptance

Publish the completed React consultation, LangGraph workflows, herb/formula API
consultation and three expert execution modes from the curated public repository.
Retain clinical review, the original knowledge mode, the department assistant and
every prescription workspace. The user explicitly requested this Git update.
Earlier implementation notes describe pre-publication work and remain historical.

Align Python/frontend package versions, lock metadata, changelog and UI source
offer with v0.3.0. Preserve the existing Git history and publish an ordinary main
commit plus a new version tag. Include source, tests, licenses and public docs.
Exclude the original corpus, patient data, runtime state, credentials, generated
assets, model weights, local machine paths and local delivery documents.

Acceptance requires frontend build/typecheck/tests, Python module suites, JS state
tests, isolated synthetic smoke, working-tree and staged-index source scans, Git
whitespace checks, remote-ref verification and both GitHub CI jobs. Existing
browser and live inference receipts are summarized in the linked documents; no
additional paid inference is needed for a version-only release.

## User-visible changes

- React/TypeScript guided intake shares authenticated FastAPI APIs and versioned
  drafts with the existing workbench. This is an incremental frontend migration.
- A real LangGraph intake workflow routes source parsing, missing information and
  explicit review. It remains deterministic rather than an autonomous diagnosis.
- Herb/formula consultations support local inference and official DeepSeek/Kimi
  APIs with separate model-knowledge and original-source provenance.
- Expert collaboration adds TCM knowledge, literature evidence, pharmacy review
  and synthesis with live progress, cancellation and manual report download.
- Choose local-only, local + Kimi or all Kimi 3.1. All-Kimi requires separate
  consent for bounded public excerpts and derived reports; patient context and
  whole-library data remain excluded. Role agreement is not clinical validation.

## Verification references

[React and LangGraph](React-LangGraph-Verification.md),
[herb and formula consultation](Herb-Formula-Verification.md),
[local experts](Expert-Collaboration-Verification.md),
[hybrid experts](Hybrid-Expert-Verification.md), and
[all Kimi 3.1 experts](All-Kimi-Expert-Verification.md).

The connected local corpus is not distributed. The public checkout starts with
synthetic data; 24 private-corpus fixture checks intentionally skip. Live Kimi
probes establish the tested connection and workflow, not clinical accuracy or
future model/account availability. DeepSeek real-account readiness is unverified.

## Local release verification

- Python module runner: clinical 376, knowledge 157 discovered (24 expected
  private-fixture skips), prescription 262, release 17; all executed checks passed.
- React typecheck/build passed; Vitest passed all 7 tests.
- Assistant and knowledge state suites passed all 23 tests.
- Isolated synthetic integration smoke passed all 170 checks.
- Working-tree publication scan passed across 322 files with no findings before
  staging. Staged-index scanning and remote CI are required at publication.

The first concurrent local frontend run timed out while starting its worker, and
the first smoke run failed during service startup. Both passed when rerun in
isolation, without changing application or test behavior. The original failures
and subsequent logs are retained locally. These environment failures are not
reported as successful checks.
