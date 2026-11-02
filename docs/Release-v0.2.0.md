# Department Agent 0.2.0

The assistant turns record supplementation, public source selection and saved-case
lookup into resumable local tasks. A missing observation can be recorded with its
origin or marked unavailable. Saved draft history can be previewed and restored as
a new version, while business archival remains in the original workspaces.

## Publication scope

The user explicitly requested publishing the completed version before starting the
proposed React/LangGraph redesign. This release contains the existing FastAPI and
vanilla JavaScript application. It introduces no React, LangGraph or external model
dependency. Third-party reference archives, copied source, private data, runtime
stores, logs, credentials and local backups are excluded.

The earlier assistant documents record local development before this publication
request. Their workflow limitations still apply. The new authorization covers the
curated public-source repository and its matching version tag only.

## Release checks

Before publication, run the portable Python suites, eight JavaScript state tests,
the isolated HTTP smoke, the working-tree and staged-index source boundary checks,
and Git whitespace checks. Update package/lock metadata and the UI source offer to
the same version. Publish the ordinary main-branch commit and a new v0.2.0 tag without
rewriting existing history. Verify both GitHub CI jobs and the published references.

Existing browser verification is documented in
`Source-Informed-Assistant-Verification.md`; this release adds no interaction or
layout change. Software tests use synthetic data and do not establish clinical
accuracy. The private frozen knowledge corpus remains excluded, so its 24
corpus-dependent tests are expected to skip.
