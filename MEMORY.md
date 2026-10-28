# Project context

Created: 2026-10-27

The user requested a public Git repository for the integrated Department Agent. This repository is a fresh source-only distribution, not a mirror of a private backup or its Git history.

Three modules share a clinical-session-protected host: clinical document review and archival, source-bound public-literature questions, and the complete MingYiRx prescription workspace. The latest UI is retained. Default public data is explicitly synthetic and does not demonstrate clinical extraction accuracy.

Original project source licenses and third-party notices must be preserved. Literature, private derived reports, original clinical exports, credentials, model weights and private operation logs are not redistributable payloads for this repository.

The public demonstration must use independently generated fixtures and relative paths, preserve full prescription functionality and avoid dependencies on the author's machine. Optional real-model/corpus configuration is documented separately from the offline smoke test.

## Public release decisions

- The integrated source uses AGPL-3.0-only, matching the incorporated ClinData Relay license. MIT and OFL notices remain attached to their components.
- The synthetic knowledge path is explicit and deterministic; it is not model inference. Frozen literature and historical corpus-bound benchmarks are excluded. Tests that require the missing frozen corpus report a skip.
- The 14 prescription resources are generated under ignored work directories. Existing renderers supply the aggregate, clinical, exact-prescription and inheritance views. The report and report CSVs are invented display fixtures.
- The launcher uses only loopback services, per-run persistence and an operating-system file lock. It stops only processes it started. The integration smoke exercises clinical review, prescription revision persistence and a restart without invoking a model.
- The source link points to the matching public release tag. Publishing a modified service requires an updated source offer.
- Windows CI may return an 8.3 short path for temporary directories. Tests that mock a checkout root must resolve that root, matching production path canonicalization; the private-output location and Git-ignore guards remain unchanged.

## Workbench UI optimization - 2026-10-29

- The approved Verda-inspired concept is implemented on the local UI branch using the existing vanilla frontend. The desktop rail is 220px, the tablet rail is 76px, and phones use an accessible modal menu. Keep the existing deep-green action color and clinical semantic colors.
- Clinical source review reuses one viewer with per-field entry points, safe exact-text highlighting, wide-screen pinning, focus return and narrow-screen modal fallback. Review decisions, default acceptance and explicit archival semantics remain unchanged.
- Knowledge sources deliberately disallow framing. Keep the original protected standalone reader and show excerpts/provenance in the answer card; do not weaken CSP to embed source pages.
- The prescription workspace retains its original iframe and all 14 generated assets. Expanded canvas mode must preserve nested iframe state, respect consumed Escape events and remove owned listeners on logout. Imported collections and annotation drafts retain their distinct persistence semantics.
- Browser evidence belongs in ignored work directories. Edge full-page screenshots can transiently report a 1px viewport; use viewport screenshots for open dialogs to avoid changing responsive UI state during capture. Repeated identical clinical uploads are idempotent; browser checks should use the returned filename.
- Verification records for this iteration are summarized in docs/UI-Optimization-Verification.md. The local synthetic preview is separate from private live services and backups. The user subsequently authorized publishing the source update to GitHub; version 0.1.1 and its matching source tag identify the UI iteration. Private runtime artifacts remain excluded.
