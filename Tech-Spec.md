# Department Agent public-source distribution

Date: 2026-10-27

## Outcome

Publish a fresh, auditable repository under the authenticated owner's account, with the latest integrated UI and all three modules. Keep existing deployments and private backups intact.

## Distribution boundary

Include application source, tests, approved synthetic fixtures, source generators, dependency metadata, launch scripts, CI, licenses, contribution/security guidance and reproducible examples. Exclude private data and derived outputs, existing runtime state, full literature/translation/index collections, host paths, credentials, third-party runtime binaries and model weights. Do not copy any original Git history.

## Architecture

- `clinical/`: existing FastAPI workbench, adapters, reviewed archival flow and optimized UI.
- `knowledge/`: existing evidence module with a clearly labeled synthetic seed corpus; optional user-provided legal corpus remains local.
- `prescription/`: existing MingYiRx source and synthetic input/build pipeline retaining all original prescription surfaces.
- `scripts/`: portable preparation, launch, checks and smoke testing.
- `work/`: ignored generated demo assets and independent service state.

Reuse the current application and source renderers. Prefer minimal path/configuration seams over a framework rewrite. Preserve existing authentication, provenance, review gates and data-origin labels. Use loopback ports for the demonstration and a synthetic FHIR service. Do not advertise the demonstration as a live Medplum/OCR/clinical-model deployment.

## Acceptance criteria

1. A fresh checkout can install its declared dependencies, build clearly labeled synthetic inputs, and start all three modules without the author's source folders or databases.
2. The current Chinese UI and complete prescription navigation, import/review/save/resume, report/download surfaces remain available. Any demonstration-only synthetic report prose is labeled as such and does not become a clinical claim.
3. Clinical and prescription data retain separate identity scopes. Public literature questions do not ingest patient data.
4. Relevant upstream tests and integration checks pass under a supported interpreter. Desktop/mobile rendering and primary synthetic workflows are checked where available.
5. Dependency lock and CI reproduce the installation. Upstream licenses/notices are retained and the new project license is compatible with included source.
6. The Git index contains only reviewed public source and synthetic inputs. A release scan rejects private runtime files, credentials, host paths and unexpected data artifacts; no secrets or records are printed in scan output.
7. Publish only after the local release is concrete and verified. Confirm the remote repository visibility, commit identity and source tree after push.

## Tasks

Inventory licensing and per-module dependencies; curate source into the fresh repository; adapt synthetic builders and portable launch configuration; write honest setup/feature documentation; run focused and end-to-end verification; review the Git index; create the public repository and push the reviewed initial commit.

## Known constraints

The local backup retains missing historical PDF/page-image notes; these private-history artifacts are outside the public distribution. Clinical accuracy, fresh-machine GPU readiness, real OCR performance and hospital deployment are not established by software tests.
