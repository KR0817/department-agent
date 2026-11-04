"""Bounded model transports; credentials stay in the server process environment."""
import importlib
import copy
import json
import os
import re
import time

import httpx

API_PROVIDERS = {
    'deepseek': {'url': 'https://api.deepseek.com/chat/completions',
                 'key_env': 'DEEPSEEK_API_KEY', 'model_env': 'DEPARTMENT_DEEPSEEK_MODEL', 'model': 'deepseek-flash'},
    'kimi': {'url': 'https://api.moonshot.cn/v1/chat/completions',
             'key_env': 'MOONSHOT_API_KEY', 'model_env': 'DEPARTMENT_KIMI_MODEL', 'model': 'kimi-k2.6'},
}
API_OUTPUT_TOKENS = 4096


class ModelError(Exception):
    """Only stable codes may cross the application boundary."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def model_configuration(provider='local'):
    """Never return a key, endpoint override, environment dump or upstream error."""
    if provider in API_PROVIDERS:
        entry = API_PROVIDERS[provider]
        model = os.environ.get(entry['model_env'], entry['model'])
        configured = bool(os.environ.get(entry['key_env']))
        transport = 'https'
    elif provider == 'local':
        transport = os.environ.get('DEPARTMENT_LLM_TRANSPORT', 'docker')
        model = os.environ.get('DEPARTMENT_LLM_MODEL', 'qwen3:14b')
        configured = True
        if transport not in ('docker', 'ollama') or 'cloud' in model.lower():
            raise ModelError('invalid_model_configuration')
        if transport == 'docker' and model not in ('qwen3:4b', 'qwen3:14b'):
            raise ModelError('invalid_model_configuration')
    else:
        raise ModelError('invalid_model_configuration')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}', model):
        raise ModelError('invalid_model_configuration')
    return {'provider': provider, 'model': model, 'transport': transport, 'configured': configured}


def provider_catalog(enabled):
    result = []
    for provider in ('local', 'deepseek', 'kimi'):
        try:
            item = model_configuration(provider)
        except ModelError:
            item = {'provider': provider, 'model': '', 'configured': False, 'error': 'invalid_model_configuration'}
        result.append({**item, 'enabled': enabled and item['configured'],
                       'send_scope': 'public_question_only' if provider != 'local' else 'public_question_and_local_passages'})
    return result


def structured_request(model, prompt, content, schema, *, max_tokens=2048, context_tokens=16384):
    """Build the bounded local-format request shared by knowledge workflows."""
    request = {'model': model, 'stream': False, 'think': False, 'keep_alive': '2m',
               'options': {'temperature': 0, 'seed': 42, 'num_ctx': context_tokens, 'num_predict': max_tokens},
               'format': schema, 'messages': [{'role': 'system', 'content': prompt},
                                            {'role': 'user', 'content': json.dumps(content, ensure_ascii=False)}]}
    if len(json.dumps(request, ensure_ascii=True).encode('ascii')) > 60000:
        raise ValueError('model_request_too_large')
    return request


def structured_content(completion, model):
    """Validate the model envelope before domain-specific schema validation."""
    if (not isinstance(completion, dict) or completion.get('model') != model or completion.get('done') is not True or
            completion.get('done_reason') not in (None, 'stop')):
        raise ValueError('incomplete_model_output')
    message = completion.get('message')
    if (not isinstance(message, dict) or message.get('role') != 'assistant' or message.get('tool_calls') or
            message.get('thinking') or not isinstance(message.get('content'), str) or len(message['content']) > 16000):
        raise ValueError('invalid_model_output')
    return importlib.import_module('app.core').parse_json(message['content'])


def local_completion(request):
    """Reuse the isolated bridge or bounded loopback HTTP, with no cloud fallback."""
    config = model_configuration()
    if request['model'] != config['model']:
        raise ModelError('invalid_model_configuration')
    if config['transport'] == 'docker':
        return importlib.import_module('app.extractive').docker_completion(request)
    client = importlib.import_module('app.local_model')
    endpoint = os.environ.get('DEPARTMENT_LLM_ENDPOINT', 'http://127.0.0.1:11434')
    client.validate_endpoint(endpoint)
    inventory = client.probe(endpoint, timeout=10)
    matches = [item for item in inventory['models'] if item['name'] == config['model'] and item['local_metadata_verified']]
    if len(matches) != 1:
        raise ValueError('installed_local_model_required')
    info, _ = client.request_json(endpoint, '/api/show', {'model': config['model']}, timeout=10)
    if (not isinstance(info, dict) or info.get('remote_host') or info.get('remote_model') or
            not isinstance(info.get('details'), dict) or info['details'].get('format') != 'gguf' or
            'completion' not in info.get('capabilities', [])):
        raise ValueError('installed_local_model_required')
    completion, _ = client.request_json(endpoint, '/api/chat', request, timeout=180)
    return {'completion': completion, 'model_digest': matches[0]['digest']}


def api_completion(request, provider):
    """Consultation output cannot claim support from the local corpus."""
    # Reconstruct the public input so a caller cannot accidentally send corpus text.
    supplied = json.loads(request['messages'][1]['content'])
    public_input = {key: supplied[key] for key in ('kind', 'subject', 'question')}
    public_input['passages'] = []
    schema = copy.deepcopy(request['format'])
    schema['$defs']['AnswerSection']['properties']['evidence_ids'].update(
        items={'type': 'string'}, maxItems=0)
    return _public_api_completion(request, provider, schema, public_input)


def api_reference_completion(request):
    """Kimi reference role receives public fields only, never other role reports."""
    supplied = json.loads(request['messages'][1]['content'])
    public_input = {key: supplied[key] for key in ('kind', 'subject', 'question')}
    return _public_api_completion(request, 'kimi', request['format'], public_input)


def api_expert_completion(request, role, *, public_evidence_confirmed=False):
    """Transmit only explicitly authorized public excerpts and validated role fields."""
    if not public_evidence_confirmed or role not in ('tcm', 'evidence', 'pharmacy', 'synthesis'):
        raise ModelError('public_evidence_required')
    supplied = json.loads(request['messages'][1]['content'])
    public = {key: supplied[key] for key in ('kind', 'subject', 'question')}
    if role in ('evidence', 'pharmacy'):
        passages = supplied.get('passages', [])
        if len(passages) > 3 or sum(len(row['text']) for row in passages) > 2600:
            raise ModelError('public_evidence_limit')
        public['passages'] = [{'id': row['id'], 'text': row['text']} for row in passages]
    if role in ('pharmacy', 'synthesis'):
        allowed = ('tcm', 'evidence') if role == 'pharmacy' else ('tcm', 'evidence', 'pharmacy')
        public['reports'] = {}
        for name in allowed:
            if name not in supplied.get('reports', {}):
                continue
            report = supplied['reports'][name]
            public['reports'][name] = {
                'status': report['status'], 'uncertainties': report.get('uncertainties', []),
                'claims': [{key: claim[key] for key in ('id', 'text', 'basis', 'passage_id')}
                           for claim in report.get('claims', [])],
                'concerns': [{'claim_ids': row['claim_ids'], 'text': row['text']}
                             for row in report.get('concerns', [])]}
    return _public_api_completion(request, 'kimi', request['format'], public)


def _public_api_completion(request, provider, schema, public_input):
    """One HTTPS call to an official host; no redirects, retries, files or tools."""
    config = model_configuration(provider)
    if provider not in API_PROVIDERS or request['model'] != config['model']:
        raise ModelError('invalid_model_configuration')
    if not config['configured']:
        raise ModelError('api_key_missing')
    if any(not isinstance(public_input[key], str) for key in ('kind', 'subject', 'question')):
        raise ModelError('invalid_public_input')
    messages = [{'role': 'system', 'content': request['messages'][0]['content'] +
                 '\nJSON schema: ' + json.dumps(schema, ensure_ascii=True)},
                {'role': 'user', 'content': json.dumps(public_input, ensure_ascii=False)}]
    body = {'model': config['model'], 'messages': messages, 'stream': False,
            'max_tokens': API_OUTPUT_TOKENS, 'response_format': {'type': 'json_object'}}
    if provider == 'deepseek' or config['model'] in ('kimi-k2.5', 'kimi-k2.6'):
        body['thinking'] = {'type': 'disabled'}
    elif provider == 'kimi' and config['model'].startswith('kimi-k3'):
        body['reasoning_effort'] = 'low'
    entry = API_PROVIDERS[provider]
    authorization = 'Bearer ' + os.environ[entry['key_env']]
    started = time.monotonic()
    try:
        with httpx.Client(trust_env=False, follow_redirects=False,
                          timeout=httpx.Timeout(180, connect=10)) as client:
            with client.stream('POST', entry['url'], json=body,
                               headers={'Authorization': authorization, 'Content-Type': 'application/json'}) as response:
                if response.status_code != 200:
                    code = {401: 'api_authentication_failed', 403: 'api_authentication_failed',
                            402: 'api_quota_exceeded', 429: 'api_rate_limited'}.get(response.status_code, 'api_request_failed')
                    raise ModelError(code)
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 131072 or time.monotonic() - started > 180:
                        raise ModelError('api_response_limit')
        value = json.loads(raw)
    except httpx.TimeoutException:
        raise ModelError('api_timeout') from None
    except (httpx.HTTPError, OSError, ValueError, UnicodeError):
        raise ModelError('api_request_failed') from None
    try:
        choices = value['choices']
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError('invalid_choice')
        choice = choices[0]
        message = choice['message']
        if choice['finish_reason'] != 'stop' or message.get('tool_calls') or message.get('role') != 'assistant':
            raise ValueError('incomplete_response')
        # Reasoning content is neither displayed nor persisted. Model aliases may
        # resolve to versioned model names; retain the reported name separately.
        reported = value.get('model')
        if not isinstance(reported, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}', reported):
            raise ValueError('invalid_model')
        return {'completion': {'model': config['model'], 'done': True, 'done_reason': 'stop',
                               'message': {'role': 'assistant', 'content': message['content']}},
                'reported_model': reported}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ModelError('api_invalid_response') from None
