# All-Kimi expert verification

Date: 2026-11-05

The user explicitly authorized selected public literature excerpts and reports
derived from those materials to reach Kimi. Workflow v3 implements that scope
only for `all_kimi` with separate public-evidence acknowledgment. Local-only and
hybrid defaults remain unchanged. All roles require `kimi-k3.1-pro`; local source
retrieval, quote identity checks and human review remain server operations.

## Automated checks

- Module runner passed: clinical 376, knowledge 157 discovered (24 private-fixture
  skips), prescription 262 and release 17. Included 28 expert graph/job/HTTP tests.
- Assistant and knowledge state tests: 23 passed. Tests cover separate evidence
  consent, exact model selection, capability gating and independence from local
  model availability, in addition to previous cancellation/stale-response cases.
- Browser checks: 56 passed across 1440, 768 and 390-pixel layouts, using synthetic
  role outputs with the actual 229-entry catalog. Desktop selection and phone
  result screenshots were inspected. No browser errors or external browser requests.
- The real local index contains 229 sources carrying public PMID/DOI metadata.
  Metadata is a scope filter, not proof of clinical correctness or source rights.
- Tests verify four API role calls and zero local inference/configuration, no
  unacknowledged dispatch, public-source exclusions, bounded excerpts, report
  field allowlists, stripping paths/records/duplicate quotations, and downstream
  stopping after provider transport failure. Real API behavior was checked by the
  deployment probe below; synthetic tests alone do not establish external inference.

## Deployment

Controlled restart completed with the process-only credential. A live public herb
question completed all four roles in 64.789 seconds. Each call was configured as
and reported `kimi-k3.1-pro`: TCM 11.681 s, evidence 11.894 s, pharmacy 35.775 s,
and synthesis 16.611 s. TCM/evidence overlapped. One selected public passage was
sent to evidence and pharmacy; synthesis received only the filtered reports.
There were four API calls and no local inference. The 229-entry catalog,
combined-index identity and five original corpus-file hashes were unchanged.

The final live UI check used the real catalog without mocked responses: v3 and
Kimi 3.1 were present, both acknowledgment gates controlled submission correctly,
229 sources remained available and no browser script error occurred. No API
inference was dispatched by that UI-only check. The working-tree source scan
passed across 320 files with no findings.

The preceding hybrid workflow was verified live separately. Operational receipts,
source-bound outputs and screenshots are ignored under
`work/all-kimi-experts-20261105/`; no Git publication is requested.

The updated local launcher performs ownership preflight before masked input and
retains its in-memory credential across at most three owned service restarts.
It stores no credential file. Closing that launcher ends its credential lifecycle.
The supervisor loop was tested with synthetic failing/successful child processes;
inherited non-secret state survived the restart. This test did not restart the
final live service or read a real credential.
The source hashes, existing run/data directory and original literature connection
were retained during cutover. Clinical accuracy remains outside software acceptance.
