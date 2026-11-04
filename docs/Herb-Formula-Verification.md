# Herb/formula consultation verification

Date: 2026-11-03

## Implemented behavior

The existing knowledge page now offers literature, herb and formula modes.
Herb/formula requests use an explicit local, DeepSeek or Kimi provider and return
five structured educational sections. Model output and related local passages
have separate provenance. The original literature extraction and protected
source reader remain available. Configuration is described in
[Model-Configuration.md](Model-Configuration.md).

## Executed checks

| Check | Result | Scope |
| --- | --- | --- |
| Clinical regression suite | 346 passed | Full suite at the initial implementation checkpoint |
| Final consultation/provider/knowledge tests | 19 passed | Includes two provider cases added after the full-suite run |
| JavaScript state tests | 15 passed | Existing assistant and new knowledge tests; seven knowledge tests also rerun after the input styling fix |
| Integrated HTTP smoke | 170 passed | Clinical review/archival, prescription resources/revisions, assistant, LangGraph and restart persistence |
| Browser checks | 32 passed | Widths 1440, 768 and 390; actual local catalog with synthetic consultation responses |
| Secure startup script | Syntax passed | Interactive credential entry was not exercised |

Browser checks covered request scope, missing-key status, public-topic
acknowledgment, literal text rendering, overflow and page errors. The live
workbench was also opened and inspected after cutover. Synthetic browser answers
test interface behavior; they are not evidence of model performance.

## Actual model requests

| Mode | Provider/model | Observed result |
| --- | --- | --- |
| Herb | Local qwen3:14b | Five sections, related passages, 113.527 seconds |
| Formula | Local qwen3:14b | Five sections, explicit no-matching-passages status, 39.538 seconds |
| Original literature question | Local qwen3:14b | Three extracts, completed Chinese translation and original source links, 32.689 seconds |
| Kimi public-topic probe | Configured API | Authentication failure; successful inference not verified |
| DeepSeek | API | Key not configured; no real request attempted |

An initial local probe returned clarification for recognizable names. The prompt
was corrected and both local consultation probes rerun successfully. These checks
establish request/response behavior, not medical accuracy, clinical suitability
or comprehensive herb/formula coverage. Source association is not verified
support for each generated claim.

Provider tests use mocked responses to verify both HTTP contracts, minimal public
payloads, missing credentials, authentication/rate-limit failures, timeouts,
oversize/truncated output and tool-call rejection. Real API usability remains
dependent on valid credentials, model access and quota.

## Preservation and delivery

The current local workbench retained its run data and ports. Its original library
still contains 230 records, 229 local full texts, 228 retrieval-eligible sources
and 5,801 chunks. Five original catalog/index/manifest file hashes were unchanged.
The original literature question was verified on the final running workbench.

API payloads exclude the local passages, bibliography, saved drafts and patient
context. The public-topic acknowledgment and bounded pattern checks do not
constitute a validated identifier detector. Keys remain in process environment;
no key file or command-line key argument was created.

Runtime receipts, model outputs and screenshots remain in ignored local work
directories. Project MEMORY.md was updated. No Git commit, push, public release
or global-memory update was performed in this iteration.
