# Knowledge module

The public launcher uses `DEPARTMENT_KNOWLEDGE_MODE=synthetic-demo`. The authored fixture in `data/demo.json` demonstrates source display, hash binding and a fixed example response. It has no PMID, DOI, clinical claim or model call. Only its displayed example question receives the fixture response; other questions return insufficiency. It is not a medical knowledge base.

The original evidence-engine source remains in `app/`, including literal span selection, source-file integrity checks, criteria scope checks, translation checks, source renderers, offline benchmarks and loopback/local Docker transports. No original literature, translation corpus, frozen index, model weight or runtime receipt is included.

## Optional full-text mode

Use the root launcher's `--knowledge-mode fulltext` with `--knowledge-root` pointing to a separately prepared, legally held evidence project. The root must contain the `app/` package, `data/corpus.json` and the source files expected by its configured loaders. The inherited frozen-source layout uses:

- `work/fulltext-v0.13/index.json` and its bound PDF/page-image sources; known-source hashes are checked by `app/fulltext.py`.
- Optional `work/literature-v0.15/index.json`, acquisition manifest, original JATS XML and core records; `app/literature.py` rebuilds source bindings.
- Optional `work/diagnosis-v0.16/criteria-bundle/index-final.json` and its bound standard source. Its optional versioned translation additionally requires `data/criteria_zh_v016.json`.

These legacy loaders are deliberately strict and are not a generic file upload/import service. Missing or mismatched files fail closed. Do not relabel synthetic material as `real_public_documents` or weaken source hashes to make a demo pass. `app/literature.build_sidecar` and `app/criteria_sources.build_criteria_bundle` remain available for their original, constrained input contracts.

The original full-text transport expects Windows Docker Desktop's Linux named pipe, an existing `sjd-agent-model-1` container with internal-only networking and no published model port, and the helper image identity pinned in `app/extractive.py`. It does not download models. These requirements are optional full-text configuration, not prerequisites for the synthetic demonstration. A different native loopback transport exists in `app/local_model.py` for offline experiments; it is not automatically substituted into the interactive extractor.

## Tests

Run the knowledge suite from this directory using the root-managed Python environment:

```powershell
uv run --project .. python -m unittest discover -s tests -v
```

Included upstream tests cover source bindings, literal selection, translation guards, XML parsing, criteria scopes, source rendering and HTTP boundaries with synthetic fixtures. Tests requiring the undistributed original frozen standard or PDF corpus are explicitly skipped when it is absent. Historical benchmark suites tied to the undistributed evaluation catalogs are not part of this public test set; no original test-count or clinical-accuracy claim is inherited.
