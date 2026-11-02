# Assistant verification record

Date: 2026-11-02
Baseline: ac18fad7772565337705bcc05679b04fab6bf817 (v0.1.1)
State: local working-tree changes; no new Git publication.

Historical record for the first, article-based assistant iteration. The subsequent
archive-based changes and their current verification are recorded in
`Source-Informed-Assistant-Verification.md`; its isolated preview run replaces the
run named below on ports 18940/18941.

## Implemented behavior

- `#assistant` provides a bounded task router, intake completion, categorized public
  source selection, saved-case retrieval and direct links to all original modules.
- Intake reuses the existing parser. Six fields (symptoms, tongue, pulse, syndrome,
  principle and prescription) expose missing/recorded/unavailable observations and
  their origins. Original records remain separate from supplements. Reviewed
  candidates can enter the existing quick-analysis workflow.
- Explicit draft saves append account-scoped SQLite revisions. Identical retries
  are idempotent, stale writes preserve the current editor and can be explicitly
  saved as a separate draft, and existing drafts remain editable at the creation
  quota. Public source selection and case query/revision are part of draft context.
- Case retrieval searches only the current account's committed collection, returns
  match fields and provenance, and links to the original version-specific view.
- Existing clinical archival, public evidence checks, source viewer CSP, prescription
  persistence, nested pages and report resources retain their original behavior.

## Executed checks

| Check | Result |
| --- | --- |
| Portable suites (`python -B scripts/check.py`) | 325 clinical, 157 knowledge, 262 prescription and 16 release tests ran successfully; 24 knowledge cases skipped because the private frozen corpus is absent |
| Final focused assistant tests (`python -B -m unittest test_department_assistant -v`, from clinical) | 12 passed, including account isolation, strict inputs, preserved source, retry/conflict, capacity and legacy-context defaults |
| Frontend state tests (`node --test tests/assistant_state.test.cjs`) | 4 passed: concurrent edit/save, stale recognition, logout with pending save, and explicit conflict copy |
| Extended runtime smoke (`python -B scripts/smoke_test.py --port 18942 --fhir-port 18943`) | 150 checks passed, including the actual parser, supplements, source preservation, committed-case search, empty categories and restart/resume of task context |
| JavaScript parsing | `node --check` passed for assistant.js, department.js and app.js |
| Patch whitespace | `git diff --check` passed |

The portable run included the first 11 assistant tests. Subsequent context/capacity
and editor refinements were checked with the final 12 focused tests and the four
frontend state tests. The runtime smoke was extended to cover the actual assistant
flow and restart. State tests use a minimal DOM double; they do not establish layout.
An initial Windows test exposed unclosed SQLite connections; connections now close
explicitly and the affected tests passed on rerun. No dependency was added.

## Browser observations

The isolated synthetic preview was exercised through the browser, using only authored
synthetic text and the bundled synthetic knowledge fixture:

1. An intake-plus-prescription request requested explicit task selection.
2. The existing example produced three visits and eleven missing/unavailable fields.
3. A synthetic pulse observation and its clinician-origin selection were added.
4. The draft survived a page reload; recognition restored the supplement.
5. Explicit review enabled quick-analysis handoff, retaining the supplemented value.
6. Empty classics displayed an empty state. Selecting the synthetic public source
   opened the existing knowledge reader with that source selected and no question
   or patient text automatically inserted.
7. Switching between the assistant and full prescription workspace preserved the
   selected original import tab.
8. A two-visit synthetic file was uploaded through the original file picker. Its
   prescriptions and adjacent changes were checked, then the original confirmation
   flow saved collection revision 1.
9. The assistant retrieved both saved visits for `dryness`, displayed source fields,
   linked to revision 1 and noted the change from collection revision 0.
10. All nine original report/download links were visible. Runtime smoke separately
    verified all fourteen original prescription resources and their bytes.
11. Desktop (1440 x 1000), tablet (768 x 1024) and phone (390 x 844) layouts were
    visually inspected. Document scroll width matched client width at each checked
    size. The phone menu opened as a dialog and closed with Escape.
12. No console errors were recorded in the inspected preview tab. The temporary
    viewport override was reset after testing.

Screenshots, test logs and the synthetic upload fixture are retained in the ignored
`work/assistant-20261102/` directory. The visible preview is
`http://127.0.0.1:18940/#assistant`, with owned synthetic FHIR on port 18941.
The run uses `assistant-20261102`; it can be restarted with:

```powershell
uv run python scripts/start.py --port 18940 --fhir-port 18941 --run-name assistant-20261102
```

## Scope of evidence

These checks establish software workflow behavior on synthetic inputs. They do not
measure medical reasoning, extraction accuracy on real records, semantic similarity,
or physical-device usability. Search remains lexical. Classics/formula sources and
real model/corpus configuration were not added or tested. Browser download links and
HTTP resources were checked; all download/export interactions were not exhaustively
replayed. Original private services and backups were not replaced. Project MEMORY.md
was updated; global memory was not modified.
