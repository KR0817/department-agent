# Workbench UI verification

Date: 2026-10-29

## Delivered behavior

The UI update implements the approved Verda-inspired layout with the existing frontend and APIs: persistent desktop navigation, a compact tablet rail, an accessible phone menu, per-field source access and a pinnable clinical reader, explicit knowledge evidence cards, a protected standalone literature reader, and an expandable complete MingYiRx workspace. No additional frontend dependencies were introduced.

The existing patient overview, charts, filters, patient/record routes and workbench subviews remain in place. Field defaults, unsaved-change blocking, final archival confirmation, partial recovery and versioned persistence remain unchanged. Clinical and prescription identities and data-origin labels remain separate.

## Executed checks

| Check | Result |
| --- | --- |
| Portable module suites | 314 clinical, 157 knowledge, 262 prescription and 16 release/lifecycle tests discovered; 725 passed, 24 knowledge tests explicitly skipped for absent optional corpus fixtures |
| Synthetic integration smoke | 131 checks passed, including clinical archival, source attribution, all prescription assets and collection save/restart/revision persistence |
| Browser workflow regression | 126 checks passed in Edge at 1440x1000, 1280x960, 768x1024 and 390x844; no script/console errors or external requests in the workflow run |
| Boundary-state browser checks | 15 checks passed for loading announcements, an injected 503 failure, retry recovery, empty source filtering, unsupported synthetic questions and long titles |
| Nested prescription Escape checks | 8 focused checks passed, covering nested document focus, navigation/rebinding, consumed events and cleanup |
| Source and review tests | 26 focused checks passed; included in the full clinical suite |
| Knowledge and full-workspace tests | 15 focused checks passed; included in the module suite |
| JS and diff checks | app.js, department.js, ui.js and browser harness syntax checked; focused and final diff whitespace checks passed |

The 503 boundary fixture is deliberately injected and recorded separately from the error-free workflow run. Browser checks use synthetic inputs only. These results do not measure clinical extraction accuracy, model performance or physical-device usability.

## Prescription coverage

The 55-entry preservation inventory contains 49 served HTML anchors, five complete resources and one retained dynamic saved-collection route. All 14 prescription assets returned HTTP 200 and matched the baseline SHA-256 values. No files under the prescription source module or its integrated backend adapter changed. The complete iframe, quick-analysis route, standalone window and all nine report/download links remain available.

Resource and anchor coverage does not mean that every interaction in all 55 workflows was executed. The existing synthetic research report and report CSVs remain explicitly labeled QA substitutes. Private clinical exports, scientific reports, original literature, real OCR and model inference were not part of this UI verification.

## Visual review

Desktop and phone screenshots were inspected for navigation, knowledge answers, protected source pages, original prescription views and clinical comparison. Tablet and compact-desktop routes were also captured and checked for outer overflow. Dense content stays within its own scroll region, and phone source review retains its original/field switch. The pinnable reader keeps the active review accessible on wide screens. Primary controls, source text and status labels remained readable in the inspected states.

## Corrections during validation

- A proposed knowledge iframe was rejected by existing frame protections. It was removed; the protected standalone source link remains.
- Expanded prescription Escape handling originally missed nested frames. The final implementation follows same-origin nested documents and releases its listeners on navigation/logout, while respecting events handled inside the original app.
- The browser harness was corrected for Edge full-page capture's transient viewport resize, idempotent repeated uploads and asynchronous native dialog close events. Initial failures are retained locally and are not counted as passing checks.

## Evidence and rollback

Ignored local evidence is stored under `work/ui-verda-20261029/`: `unit-tests.log`, `integration-smoke.log`, `browser/checks.json`, `state-check.json`, `department-nested-escape.json`, screenshots and `preservation/prescription-coverage.csv`. The original static directory and its checksums are in `baseline-static/` and `baseline-sha256.json`. The final checksum manifest binds the checked frontend files.

Rollback of this local UI consists of restoring the complete baseline static directory as a group. It does not require rolling back clinical databases or prescription collections. The current work changes neither private deployments nor frozen backups. The source update is prepared as version 0.1.1, with the page source offer pointing to the matching Git tag. Publishing this source does not replace private live sites.
