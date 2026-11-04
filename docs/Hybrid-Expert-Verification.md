# Hybrid expert verification

Date: 2026-11-05

## Implemented behavior

Workflow v2 adds an explicit local + Kimi choice. Kimi handles the public TCM
reference subtask concurrently with local evidence retrieval analysis; local
pharmacy and synthesis follow the join. The original local-only and single-model
paths remain. Kimi receives no local passages, source metadata or role reports.
Each hybrid job makes at most one API call, with no automatic retry/fallback.
See [the contract](Hybrid-Expert-Tech-Spec.md) and [usage](Expert-Collaboration.md).

## Automated checks

- Full module runner passed: clinical 371 tests, knowledge 157 discovered
  (24 skipped because private corpus fixtures are excluded), prescription 262,
  release 17. This includes 23 expert graph/job/HTTP tests and 16 consultation tests.
- Assistant and knowledge JS state suites: 21 tests passed, including mixed-model
  selection, acknowledgment, model labels, old-server capability checks and
  cancellation on provider changes.
- Browser checks: 53 passed at 1440, 768 and 390 pixels. These used synthetic
  role completions with the real 229-entry local catalog. Screenshots were
  inspected at desktop and phone widths; source quotations, partial failures,
  manual review/export and original mode switching were preserved.
- Concurrency tests use synchronization barriers/events to establish overlapping
  reference calls and downstream joins. Failure tests cover provider isolation,
  cancellation, source changes, no retries, ownership and disabled tracing.
- HTTP boundary tests use synthetic markers for corpus, reports and case data;
  none cross the API boundary. K3 low-reasoning parameters are checked, and
  returned reasoning text is discarded. No real key is present in test fixtures.
- Isolated integration smoke passed all 170 checks, including clinical archival,
  prescription persistence, original mode availability and restart behavior.
- Working-tree source scan passed with no findings (318 files at this checkpoint).
  This is a filename/text check, not a medical or redistribution-rights assessment.

## Runtime boundary

After controlled restart, a real public herb question completed all four roles
in 140.643 seconds: Kimi 3.1 TCM 11.419 s, local evidence 50.433 s, local pharmacy
57.746 s and local synthesis 31.880 s. Reference calls overlapped. Exactly one
Kimi request and three qwen3:14b requests were recorded; the upstream Kimi model
was `kimi-k3.1-pro`. The 229-entry catalog, combined-index digest and five original
corpus-file hashes were unchanged. This establishes execution, not clinical accuracy.

The first live job correctly returned partial results because Docker Desktop was
stopped: Kimi completed, local evidence failed, and later local calls were skipped.
Starting the installed Docker Desktop restored the existing isolated model
container; a local connection probe passed before the successful second job.
No model was downloaded, no source was changed and no automatic API retry occurred.

The initial cutover was refused because the old launcher process had exited while
its child services remained alive. The old service was left running; no hybrid
API request was dispatched. The corrected operational script validates the
recorded host executable/arguments and actual listener parentage before asking
for a credential, and rechecks ownership immediately before cutover.

The original library, run name and data directory must remain unchanged. Local
operational scripts, screenshots, receipts and model outputs are ignored under
`work/hybrid-experts-20261105/`. No publication is part of this iteration.
Model agreement, source identity and successful execution do not validate
clinical accuracy; the trial label and human review remain required.
