"""Deterministic workflow scenarios layered on the unchanged synthetic cohort."""
from care import signal_key, summarize_plans

VERSION = 'care-scenarios-v1'


def scenarios(patient, as_of):
    number = int(patient['id'].rsplit('-', 1)[1])
    plan = {'id': 'SIM-PLAN-' + str(number), 'due_date': '2026-10-24', 'window_start': '2026-10-10',
            'window_end': '2026-11-07', 'completed': False, 'evidence': [], 'cancelled': False,
            'sync_error': None, 'queue_status': 'synthetic_only'}
    if number <= 16:
        plan.update(completed=True, evidence=['visit:' + patient['visits'][-1]['id']])
    elif number <= 26:
        plan.update(due_date='2026-09-15', window_start='2026-09-01', window_end='2026-09-29')
    elif number <= 36:
        # This plan is created after the latest recorded visit; that visit cannot fulfill it.
        plan.update(due_date='2026-11-07', window_start='2026-10-24', window_end='2026-11-21',
                    index_date=patient['last_visit'])
    elif number <= 46:
        plan.update(due_date='2027-01-22', window_start='2027-01-08', window_end='2027-02-05')
    elif number <= 48:
        plan.update(cancelled=True)
    plans = [plan] if number <= 48 else []
    history = []
    if number in (4, 5, 6):
        item = next(i for i in patient['attention']['items'] if i['level'] == 'red')
        state = {4: 'reviewed', 5: 'acknowledged', 6: 'in_progress'}[number]
        history.append({'patient_id': patient['id'], 'kind': 'attention', 'item_id': signal_key(patient['attention'], item),
                        'revision': 0, 'actor': 'synthetic-scenario', 'recorded_at': as_of + 'T00:00:00+08:00',
                        'body': {'state': state, 'owner': '\u5408\u6210\u590d\u6838\u5458', 'due_date': None,
                                 'note': '\u5408\u6210\u573a\u666f\uff1a\u6f14\u793a\u5904\u7406\u72b6\u6001\u4e0e\u539f\u59cb\u4f18\u5148\u7ea7\u5206\u5f00\u4fdd\u5b58\u3002',
                                 'disposition': 'already_managed' if state == 'reviewed' else '',
                                 'evidence_note': '\u5408\u6210\u5904\u7f6e\u8bb0\u5f55\uff0c\u4ec5\u7528\u4e8e\u754c\u9762\u6d4b\u8bd5\uff0c\u4e0d\u4ee3\u8868\u771f\u5b9e\u533b\u751f\u5904\u7f6e\u3002',
                                 'evidence_refs': ['visit:' + item['evidence'][0]['event_id']], 'source_snapshot': item}})
    if number in (29, 30, 31):
        title = {29: '\u5408\u6210\u573a\u666f\uff1a\u8f6c\u9662\u540e\u5f85\u8865\u8d44\u6599',
                 30: '\u5408\u6210\u573a\u666f\uff1a\u6682\u672a\u53d6\u5f97\u8054\u7cfb',
                 31: '\u5408\u6210\u573a\u666f\uff1a\u5386\u53f2\u8d44\u6599\u8fdf\u5230'}[number]
        history.append({'patient_id': patient['id'], 'kind': 'event', 'item_id': 'SIM-EVENT-' + str(number),
                        'revision': 0, 'actor': 'synthetic-scenario', 'recorded_at': as_of + 'T00:00:00+08:00',
                        'body': {'category': 'other', 'date': '2026-09-10', 'end_date': None, 'title': title,
                                 'details': '\u8bb0\u5f55\u4e8b\u4ef6\u65e5\u671f\u548c\u5f55\u5165\u65e5\u671f\u4ee5\u6f14\u793a\u8fdf\u5230\u8d44\u6599\u3002',
                                 'source_type': 'unknown', 'drug_name': '', 'dose': '', 'frequency': '', 'route': '',
                                 'status': 'unknown', 'site': '', 'merged_into': None, 'note': title, 'evidence_refs': []}})
    return summarize_plans(plans, as_of), history
