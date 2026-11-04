"""Local, source-bound consultation turns; durable drafts stay in the host store."""
from operator import add
from typing import Annotated, TypedDict

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from department import invoke
from department_assistant import apply_supplements, choice, exact, validate_draft


class ConsultationState(TypedDict, total=False):
    draft: dict
    action: str
    prepared: dict
    counts: dict
    question: dict | None
    stage: str
    trace: Annotated[list[str], add]


PROMPTS = {
    'symptoms': '\u8bf7\u8865\u5145\u672c\u6b21\u4e3b\u8981\u4e0d\u9002\u3001\u51fa\u73b0\u65f6\u95f4\u53ca\u53d8\u5316\uff0c\u5e76\u6ce8\u660e\u4fe1\u606f\u6765\u6e90\u3002',
    'tongue': '\u8bf7\u8bb0\u5f55\u5df2\u6709\u7684\u820c\u8c61\u89c2\u5bdf\uff1b\u5c1a\u65e0\u8d44\u6599\u65f6\u53ef\u9009\u62e9\u65e0\u6cd5\u63d0\u4f9b\u3002',
    'pulse': '\u8bf7\u8bb0\u5f55\u533b\u751f\u5df2\u786e\u8ba4\u7684\u8109\u8c61\uff1b\u5c1a\u65e0\u8d44\u6599\u65f6\u53ef\u9009\u62e9\u65e0\u6cd5\u63d0\u4f9b\u3002',
    'syndrome': '\u8bf7\u8865\u5f55\u5df2\u6709\u75c5\u5386\u6216\u533b\u751f\u786e\u8ba4\u7684\u8bc1\u5019\uff1b\u5c1a\u672a\u786e\u8ba4\u65f6\u53ef\u9009\u62e9\u65e0\u6cd5\u63d0\u4f9b\u3002',
    'principle': '\u8bf7\u8865\u5f55\u533b\u751f\u5df2\u8bb0\u5f55\u7684\u6cbb\u6cd5\uff1b\u5c1a\u65e0\u8d44\u6599\u65f6\u53ef\u9009\u62e9\u65e0\u6cd5\u63d0\u4f9b\u3002',
    'prescription': '\u8bf7\u6309\u5df2\u6709\u5904\u65b9\u539f\u6587\u8865\u5f55\uff1b\u5c1a\u65e0\u5904\u65b9\u65f6\u53ef\u9009\u62e9\u65e0\u6cd5\u63d0\u4f9b\u3002',
}


async def recognize(state: ConsultationState):
    draft = state['draft']
    raw = (await invoke('mingyirx', 'recognize', {'text': draft['text'], 'data_origin': draft['data_origin']})
           if draft['text'].strip() else {'records': [], 'warnings': []})
    return {'prepared': apply_supplements(raw, draft), 'trace': ['recognize']}


def assess(state: ConsultationState):
    missing = state['prepared']['missing']
    counts = {name: sum(item['status'] == status for item in missing)
              for name, status in [('pending', 'not_asked'), ('recorded', 'recorded'), ('unavailable', 'unavailable')]}
    if state['action'] == 'review' and (counts['pending'] or not state['prepared']['records']):
        raise HTTPException(409, 'Complete source collection before review')
    return {'counts': counts, 'trace': ['assess']}


def next_node(state: ConsultationState):
    if not state['prepared']['records']:
        return 'request_source'
    return 'ask_question' if state['counts']['pending'] else 'review'


def ask_question(state: ConsultationState):
    item = next(item for item in state['prepared']['missing'] if item['status'] == 'not_asked')
    return {'stage': 'question', 'question': {'record_id': item['record_id'], 'field': item['field'],
                                             'prompt': PROMPTS[item['field']]}, 'trace': ['ask_question']}


def request_source(state: ConsultationState):
    return {'stage': 'need_source', 'question': None, 'trace': ['request_source']}


def review(state: ConsultationState):
    return {'stage': 'reviewed' if state['action'] == 'review' else 'review_ready',
            'question': None, 'trace': ['review']}


builder = StateGraph(ConsultationState)
for name, node in [('recognize', recognize), ('assess', assess), ('ask_question', ask_question),
                   ('request_source', request_source), ('review', review)]:
    builder.add_node(name, node)
builder.add_edge(START, 'recognize')
builder.add_edge('recognize', 'assess')
builder.add_conditional_edges('assess', next_node, ['request_source', 'ask_question', 'review'])
for name in ('request_source', 'ask_question', 'review'):
    builder.add_edge(name, END)
graph = builder.compile()


async def consultation(value):
    exact(value, 'action draft')
    action = choice(value['action'], ('advance', 'review'))
    draft = validate_draft(value['draft'])
    if draft['task'] != 'intake':
        raise HTTPException(422, 'Consultation requires an intake draft')
    # Explicitly disable external tracing even when the host has tracing enabled.
    with tracing_context(enabled=False):
        result = await graph.ainvoke({'draft': draft, 'action': action, 'trace': []},
                                    config={'recursion_limit': 8, 'callbacks': []})
    return {key: result[key] for key in ('prepared', 'counts', 'question', 'stage', 'trace')} | {
        'engine': 'langgraph', 'model_called': False, 'clinical_approval': None}
