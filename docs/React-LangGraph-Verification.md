# React and LangGraph verification

Date: 2026-11-02
Source: local 0.3.0.dev0 working tree, based on published v0.2.0 (`38ab91a`).

## Delivered behavior

The new `/#consultation` workspace is implemented in React 19.3.1 and strict
TypeScript, compiled with Vite 8.3.5. The existing FastAPI host provides the JSON
API and serves local production assets without changing its CSP or session boundary.
The original assistant and clinical, knowledge and prescription pages remain
available. This is an incremental React adoption, not a complete legacy rewrite.

LangGraph 1.2.19 executes a compiled StateGraph for each turn. Actual node results
drive source collection, missing-field questions and the explicit review stage.
The graph uses the existing deterministic parser and six observation fields. It
does not invoke an LLM, synthesize a diagnosis, recommend a prescription or claim
clinical accuracy. External LangSmith tracing is explicitly disabled.

The existing append-only, account-scoped draft API stores source text and
observations. Restoring history appends a new version after explicit saving.
Reopening a draft reconstructs the next graph turn. No separate graph checkpoint
database or LangGraph interrupt persistence is claimed. Handoff preserves source
hashes/evidence and still requires the original business review/save workflow.

## Executed checks

| Check | Observed result |
|---|---|
| Locked frontend reinstall | `npm --prefix frontend ci --ignore-scripts --no-audit --no-fund` passed |
| Strict TypeScript and production build | `npm --prefix frontend run build` passed |
| React DOM and session-state tests | 7 passed; cancellation, stale responses, navigation during save, logout, dirty recovery, history and human review |
| Existing assistant JavaScript suite | 8 passed |
| Python module runner | Passed: 332 clinical, 157 knowledge, 262 prescription and 17 release/tooling tests |
| Knowledge test coverage boundary | 24 of the 157 tests skipped because the private frozen corpus is intentionally absent |
| Actual LangGraph tests | Included in the clinical suite; graph branches, multi-turn progression, strict input, stale IDs, review prerequisites, source preservation and tracing disabled |
| Isolated HTTP smoke | 170 checks passed, including graph restart/resume, source preservation and all 14 prescription resources |
| New browser regression | 108 checks passed at 1440, 768 and 390 px widths; no console/page errors, no external requests, no outer overflow |
| Original browser regression | 126 checks passed at desktop/compact/tablet/mobile sizes; no console/page errors or external requests |
| Frontend runtime dependency audit | No findings from `npm audit --omit=dev` |
| Working-tree source boundary scan | Passed with no findings; generated React bundles and node_modules are excluded |
| Syntax/whitespace checks | Updated host/browser scripts and Git diff passed |

The browser regression covers actual authenticated HTTP calls, synthetic source
entry, a recorded answer with provenance, cancellation with a deliberately delayed
response, navigation without losing the answer, explicit saves, reopening a task,
history preview/restoration, unavailable fields, manual review, handoff into editable
visit controls, original prescription pages and logout cleanup. Desktop and mobile
screenshots were inspected. Mobile action labels were adjusted to avoid awkward
single-character wrapping.

An initial parallel startup collided with the existing preparation lock; the final
module runner was run serially and passed. Lifecycle-test fixtures were updated to
include the required frontend assets and graph resume response. The first handoff
browser assertion incorrectly inspected text nodes for values in editable controls;
it now checks the actual textarea values. These were verification fixes, not waived
checks.

## Evidence and deployment boundary

Ignored evidence is under `work/react-langgraph/`: browser screenshots/results,
original UI results, final module and smoke logs, and the working-tree scan. The
browser scripts accept only an explicitly synthetic loopback service.

The local preview runs separately from private services. No private database,
credential, corpus, original patient record or reference archive was included.
The public v0.2.0 tag is unchanged. This iteration has not been published, so the
updated GitHub CI configuration has not yet run remotely. Tests and build ran
locally on Windows; the prior release's cloud checks are not evidence for this
unpublished source.

## Implementation references

- [React with an existing backend](https://react.dev/learn/build-a-react-app-from-scratch)
- [Vite backend integration](https://vite.dev/guide/backend-integration)
- [LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangSmith tracing context](https://reference.langchain.com/python/langsmith/run_helpers/tracing_context)
