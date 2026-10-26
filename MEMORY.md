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
