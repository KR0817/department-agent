# Knowledge consultation model configuration

The knowledge page contains Literature Q&A, Herb consultation and Formula
consultation. The original extractive literature workflow remains unchanged.
Herb/formula answers have five sections: identity, traditional properties or
composition, applications/research, cautions/interactions, and uncertainty.
These are model-generated educational summaries, not verified monographs.

## Providers

| UI provider | Server configuration | Default model | Transport |
| --- | --- | --- | --- |
| Local | `DEPARTMENT_LLM_TRANSPORT`, `DEPARTMENT_LLM_MODEL` | `qwen3:14b` | Existing isolated Docker helper by default |
| DeepSeek API | `DEEPSEEK_API_KEY`, optional `DEPARTMENT_DEEPSEEK_MODEL` | `deepseek-flash` | `https://api.deepseek.com/chat/completions` |
| Kimi API | `MOONSHOT_API_KEY`, optional `DEPARTMENT_KIMI_MODEL` | `kimi-k2.6` | `https://api.moonshot.cn/v1/chat/completions` |

Provider metadata exposes only configuration presence, never the key. Presence
does not establish that a key is valid or has available quota. API requests use
the official HTTPS hosts without redirects, proxy inheritance or retries. The
server accepts no browser-supplied endpoint, model override, API key, tool call,
patient context, conversation history, file or attachment.

For direct local Ollama, set `DEPARTMENT_LLM_TRANSPORT=ollama` and
`DEPARTMENT_LLM_ENDPOINT=http://127.0.0.1:11434`. Only numeric loopback endpoints
are accepted. The installed model must be verifiably local GGUF with completion
capability; cloud-backed Ollama entries are refused. The existing Docker bridge
supports its pinned qwen3:4b and qwen3:14b models. This feature does not download
models or expose a model port.

## Enter API keys without putting them in command history

On Windows, use the included script in a local PowerShell terminal. It reads keys
with hidden input, passes them only through the server process environment, and
restores the parent environment when the launcher exits. No key file is created.

```powershell
.\scripts\Start-WithApi.ps1 -Provider both -KnowledgeRoot 'F:\path\to\validated-knowledge-project' -RunName api-models -Port 18894 -FhirPort 18895
```

Choose `deepseek` or `kimi` instead of `both` to configure one provider. Do not
paste keys into chat, source files, screenshots or command arguments. Do not
commit credential files. Existing running processes do not inherit changes to
their parent's environment. To retain an existing workspace, reuse its run name,
knowledge root and ports after closing only that workspace's own launcher.
The script refuses occupied ports and never stops unrelated services.

To select Kimi 3.1 for a local deployment, set this non-secret model override in
the launcher terminal before starting the service:

```powershell
$env:DEPARTMENT_KIMI_MODEL = 'kimi-k3.1-pro'
```

The existing K3 transport sends `reasoning_effort=low` with JSON output and does
not send the K2 `thinking` switch. This changes that process's selected model;
the package fallback remains K2.6. Credentials entered through the masked
launcher are process-only. Keep the launcher open; after it closes or the
machine restarts, enter the key again rather than expecting a saved credential.

The public synthetic demo performs no medical inference. Consultation is enabled
with the validated fulltext knowledge mode, using the same original source root
as literature Q&A. Keep machine-specific startup settings under ignored `work/`.

## What is sent

Local mode receives the explicit name, current public question and up to three
complete relevant passages. Selection uses literal subject matching followed by
existing lexical ranking. A Chinese name will not automatically match every
English synonym; choose an explicit name found in the corpus when appropriate.
The rheumatology collection is not a comprehensive herb/formula database.

Single-model DeepSeek/Kimi and mixed-mode Kimi receive only the explicit name and current public question, plus
the application instructions and response schema. They receive no library
passages, bibliography, patient records or saved drafts. The UI requires a
public-topic acknowledgment; the server rejects identifying patterns and scoped
personal-prescribing requests. These bounded controls are not a validated PHI
detector. Only enter general knowledge questions.

The separately selected **All Kimi 3.1** expert mode requires additional consent
for selected public literature excerpts and derived role reports. It uses at most
four `kimi-k3.1-pro` calls, without local model inference. Excerpts are bounded to
three complete passages totaling 2,600 characters. Source paths, whole-library
content, patient records and saved drafts are excluded. See the
[all-Kimi contract](All-Kimi-Expert-Tech-Spec.md) for role-specific input boundaries.

In single-model API answers, related literature is still retrieved and shown locally. It is
labeled separately and is not presented as evidence the external model used.
All bibliographic metadata and links come from the original local index.
Generated references, unknown evidence IDs, incomplete JSON and numerical dose
instructions are rejected. The application does not persist questions or answers.

## HTTP example

Use an authenticated same-origin session. Read the current catalog first and
include its `index_sha256` in `POST /api/department/knowledge/consult`:

```json
{
  "kind": "herb",
  "subject": "Glycyrrhiza",
  "question": "Summarize traditional uses and cautions without doses.",
  "provider": "deepseek",
  "public_topic_confirmed": true,
  "disease": "all",
  "source_id": "all",
  "index_sha256": "COPY_THE_CURRENT_CATALOG_DIGEST"
}
```

Use `kind=formula` for formula consultations. Only one request runs at a time in
this local workbench; a concurrent request returns `busy`. Stopping browser
waiting discards late results but may not stop a server-side or billable API call.
No automatic retry or alternate-provider fallback is performed.

## Verification boundary

Transport-contract tests use mocked API responses and synthetic data. Real API
readiness additionally requires a working key, permitted model and quota; a
successful software test does not establish medical correctness. Failed calls
return sanitized configuration, authentication, quota, rate-limit, timeout or
format status without upstream response bodies, request text or secrets.

On 2026-11-05, a user-entered China open-platform key was verified through the
official model-list endpoint, then used by the existing local workbench with
`DEPARTMENT_KIMI_MODEL=kimi-k3.1-pro`. One fixed public herb question returned an
accepted five-section answer in 24.586 seconds; the upstream reported model was
also `kimi-k3.1-pro`. The local catalog retained 229 full texts. This verifies
that deployment's authentication, model selection and request/response path at
that time, not clinical answer accuracy or future account availability. Receipts
remain outside the public source under ignored `work/`.

## Official references checked for this implementation

- [Ollama chat](https://docs.ollama.com/api/chat) and [structured outputs](https://docs.ollama.com/capabilities/structured-outputs).
- [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/), [models](https://api-docs.deepseek.com/quick_start/pricing/) and [JSON output](https://api-docs.deepseek.com/guides/json_mode/).
- [Kimi Chat Completions](https://platform.kimi.com/docs/api/chat). The default K2.6 request disables thinking; configurable K3 models use low reasoning effort. Reasoning content is not displayed or stored.
