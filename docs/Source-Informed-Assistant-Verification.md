# Source-informed assistant verification

Date: 2026-11-02
Status: local source changes and isolated synthetic preview; no Git push.
Reference archive and design: `Source-Informed-Assistant-Plan.md`.

## Implemented

- Guided six-field supplementation with separate unasked, recorded and unavailable
  counts, explicit origin, empty-answer rejection and an all-fields review mode.
- Account-owned immutable revision history, 20-item keyset pages, selected-version
  preview and explicit recovery into an editable draft. Saving appends a revision.
- Actual operation state for planning, recognition and saved-case search. Cancelling
  browser waiting preserves edits and discards even a late successful response.
- Human-readable history preview with expandable source and supplement provenance.
- Existing v1 drafts, review gates, source evidence, original workspace and services
  retain their boundaries. No new runtime dependency or upstream code was imported.

## Executed checks

| Check | Observed result |
| --- | --- |
| Focused assistant Python tests | 13 passed, including history pagination, ownership, recovery append, immutable previous versions and stale writes |
| Portable clinical suite | 327 tests passed |
| Portable knowledge suite | 157 tests ran successfully; 24 skipped for the absent private frozen corpus |
| Portable prescription suite | 262 tests passed |
| Release/tooling suite after fixture correction | 16 passed |
| Final JavaScript state suite | 8 passed, including cancellation, guided answers, historical recovery and unsaved-edit protection |
| Actual integration smoke | 157 checks passed; original 14 prescription resources, five analysis pages, clinical archival, public source, version append and restart recovery included |
| JavaScript syntax and patch whitespace | `node --check clinical/static/assistant.js` and `git diff --check` passed |

The first portable run failed two smoke-lifecycle tests: their mocked orchestration
had not modeled the assistant workflow added in the previous iteration. The fixture
now supplies that workflow and its restart result; all 16 tooling tests passed on
rerun. The actual HTTP smoke independently passed. The first combined command is
retained as a failed run, not relabeled as successful. No application behavior was
changed to satisfy the lifecycle fixture.

State tests execute the actual assistant module with a small DOM test double; layout
is checked separately. Existing framework tests emit a Starlette/httpx deprecation
warning; no dependency upgrade was made in this feature change.

## Browser checks

The preview uses only the bundled synthetic records, with no model request:

1. Three visits produced eleven pending fields. Empty confirmation was rejected.
2. A synthetic pulse observation with clinician origin advanced the queue; marking
   the next field unavailable produced 9 unasked, 1 recorded and 1 unavailable.
3. Draft revisions 1 and 2 were saved. Version 1 was previewed and explicitly loaded;
   saving appended revision 3. Refresh and reopen retained supplements and resumed
   the unresolved field. The handoff remained disabled until explicit review.
4. All-fields mode exposed the saved observation and unavailable status correctly.
5. The revised history preview displayed readable task/source/observation labels,
   including expandable source provenance, on the phone layout.
6. Desktop 1440 x 1000, phone 390 x 844 and tablet 768 x 1024 were inspected. Measured
   document scroll/client widths matched at each size. Screenshots show the actual
   synthetic UI; they are not generated mockups.
7. The original MingYiRx iframe loaded with its aggregate/import/case navigation,
   detailed prescription comparison and all nine report/download links. HTTP smoke
   verified the original resources independently.
8. No errors were present in the inspected browser console log. The temporary
   viewport override was reset and the preview tab retained as a deliverable.

Browser cancellation races were verified with deterministic frontend state tests;
no claim is made that an arbitrary server task is interrupted. Model correctness,
real clinical extraction, device hardware behavior and all possible downloads were
not evaluated. Upstream code was inspected, not run.

## Reproduce and evidence

Logs, a pre-change source snapshot, screenshots and a source-hash manifest are under
ignored `work/source-review-20261102/`. The revised browser preview is
`http://127.0.0.1:18940/#assistant`; owned synthetic FHIR uses 18941.

```powershell
uv run python scripts/start.py --port 18940 --fhir-port 18941 --run-name source-review-20261102
uv run python -B -m unittest discover -s clinical -p test_department_assistant.py -v
node --test tests/assistant_state.test.cjs
uv run python -B scripts/smoke_test.py --port 18942 --fhir-port 18943
```

Use free ports when reproducing; the launcher rejects occupied ports. The previous
article-based record remains in `Assistant-Verification.md`. Project MEMORY.md and
the separate source-review context were updated. Global memory, private services,
backups and public Git refs were not modified.
