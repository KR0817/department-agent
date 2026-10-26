"""Deterministic review priorities from archived evidence, never clinical diagnoses."""
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata

RULES_VERSION = 'attention-v1'
LEVELS = {'gray': 0, 'yellow': 1, 'orange': 2, 'red': 3}
TEXT_CODES = {'medications', 'prescription', 'inpatient_exams', 'infection_status', 'comorbidities', 'baseline_exams', 'diagnosis', 'syndrome'}
SCORES = {'dryness': '\u53e3\u5e72\u8bc4\u5206', 'fatigue': '\u75b2\u52b3\u8bc4\u5206', 'pain': '\u75bc\u75db\u8bc4\u5206'}
LABELS = {
    'igg': r'(?<![A-Za-z0-9_])IgG(?![A-Za-z0-9_])|\u514d\u75ab\u7403\u86cb\u767d\s*G',
    'c3': r'(?<![A-Za-z0-9_])C3(?![A-Za-z0-9_])|\u8865\u4f53\s*C3', 'c4': r'(?<![A-Za-z0-9_])C4(?![A-Za-z0-9_])|\u8865\u4f53\s*C4',
    'dryness': r'\bdryness\b|\u53e3\u5e72|\u5e72\u71e5',
    'fatigue': r'\bfatigue\b|\u75b2\u52b3', 'pain': r'\bpain\b|\u75bc\u75db',
    'saliva': r'\bsaliva\b|\u553e\u6db2\u6d41\u7387',
    'schirmer_left': r'\bschirmer_left\b|\u5de6\u773c',
    'schirmer_right': r'\bschirmer_right\b|\u53f3\u773c',
}
NAMES = {'igg': 'IgG', 'c3': '\u8865\u4f53C3', 'c4': '\u8865\u4f53C4',
         'saliva': '\u553e\u6db2\u6d41\u7387', 'schirmer_left': '\u5de6\u773c\u6cea\u6db2\u8bd5\u9a8c',
         'schirmer_right': '\u53f3\u773c\u6cea\u6db2\u8bd5\u9a8c', **SCORES}
CRITICAL = re.compile(r'\u5371\u6025(?:\u503c|\u7ed3\u679c|\u63d0\u793a)|\bcritical\s+(?:value|result)\b', re.I)
RECURRENT = re.compile(r'\u53cd\u590d\u611f\u67d3|\u9891\u7e41\u611f\u67d3|\brecurrent\s+infection\b', re.I)
AMBIGUOUS = re.compile(r'\u65e0|\u672a|\u5426\u8ba4|\u975e\u5371\u6025|\u4e0d(?:\u662f|\u5b58\u5728|\u8003\u8651)|\u6392\u9664|\u5f85\u6392|\u7591\u4f3c|\u53ef\u80fd|\u8003\u8651|\u5efa\u8bae\u89c2\u5bdf|\u662f\u5426|\u5982(?:\u679c|\u51fa\u73b0)|\u82e5|\u65e2\u5f80|\u66fe(?:\u7ecf|\u6709)|\u5386\u53f2|\u5df2(?:\u89e3\u9664|\u5904\u7406|\u63a7\u5236|\u590d\u6838|\u590d\u67e5|\u6062\u590d)|\u6bcd\u4eb2|\u7236\u4eb2|\u5bb6\u5c5e|\u4ed6\u4eba|\u5ba3\u6559|\u6559\u80b2|[\u201c\u201d\u2018\u2019\"\u300c\u300d]|\b(?:no|not|denies|suspected|possible|history|resolved|if|mother|father|family)\b', re.I)
COUNT = re.compile(r'\u8fd1\s*(\d+)\s*\u5929\u611f\u67d3\s*(\d+)\s*\u6b21\s*[,\uff0c;\uff1b]\s*\u524d\s*(\d+)\s*\u5929\u611f\u67d3\s*(\d+)\s*\u6b21')
REFERENCE = re.compile(r'(?:\u53c2\u8003(?:\u8303\u56f4|\u533a\u95f4|\u503c)|reference\s+(?:range|interval))\s*[:\uff1a=]?\s*([+-]?\d+(?:\.\d+)?)\s*(?:-|~|\u301c|\uff5e|\u2013|\u2014|\u81f3)\s*([+-]?\d+(?:\.\d+)?)\s*([A-Za-z\u5206]+(?:/[A-Za-z0-9]+)?)', re.I)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Attention requires an explicit ISO date')
    return dt.date.fromisoformat(value)


def _number(value):
    if not isinstance(value, str) or not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value.strip()):
        return None
    try:
        result = Decimal(value.strip())
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def _unit(code, unit):
    unit = unit.strip()
    if code in SCORES and unit in ('', '\u5206'):
        return '\u5206'
    return {'g/l': 'g/L', 'mg/dl': 'mg/dL', 'g/dl': 'g/dL', 'ml/min': 'mL/min'}.get(unit.lower(), unit)


def _ambiguous(text):
    # Pending handling and explicit confirmation do not negate a critical report.
    remaining = re.sub(r'(?:\u5c1a)?\u672a(?:\u5904\u7406|\u5904\u7f6e)|\u5df2\u590d\u6838\u786e\u8ba4', '', text)
    return bool(AMBIGUOUS.search(remaining) or re.search(r'\u8bef\u62a5|\u5df2\u6b63\u5e38', remaining))


def _scope(evidence):
    """Read the matched CSV note or one explicitly identified ordinary-text item."""
    code, value, quote = (evidence[key] for key in ('code', 'value', 'quote'))
    if code in TEXT_CODES:
        return value if value in quote else None
    label = LABELS.get(code)
    if not label:
        return None
    try:
        rows = list(csv.reader(quote.splitlines()))
    except csv.Error:
        return None
    is_csv = len(rows) == 1 and len(rows[0]) >= 6 and evidence['date'] in rows[0]
    if is_csv:
        row = rows[0]
        indices = [i for i in range(3, len(row) - 2)
                   if row[i:i + 3] == [code, value, evidence['unit']]]
        if len(indices) != 1 or indices[0] + 3 >= len(row):
            return None
        note = ','.join(row[indices[0] + 3:])
        if not re.search(label, note, re.I):
            return None
        text = note
    else:
        anchor = '(?:' + label + r')\s*(?:\u8bc4\u5206|score)?\s*[:\uff1a=]?\s*' + re.escape(value) + r'(?![\w.])'
        if not re.search(anchor, quote, re.I):
            return None
        text = quote
    if any(other != code and re.search(pattern, text, re.I) for other, pattern in LABELS.items()):
        return None
    return text


def _flatten(visits, as_of, limitations):
    facts, dates, seen = [], set(), set()
    for visit in visits if isinstance(visits, list) else []:
        if not isinstance(visit, dict):
            limitations.add('\u90e8\u5206\u5f52\u6863\u8bb0\u5f55\u683c\u5f0f\u4e0d\u5b8c\u6574\uff0c\u9700\u6838\u5bf9\u539f\u4ef6\u3002')
            continue
        try:
            day = _date(visit.get('date'))
        except ValueError:
            limitations.add('\u90e8\u5206\u8bb0\u5f55\u65e5\u671f\u65e0\u6548\uff0c\u672a\u53c2\u4e0e\u5224\u5b9a\u3002')
            continue
        if day > as_of:
            limitations.add('\u622a\u9762\u65e5\u671f\u4e4b\u540e\u7684\u8bb0\u5f55\u672a\u53c2\u4e0e\u5224\u5b9a\u3002')
            continue
        dates.add(day.isoformat())
        for fact in visit.get('facts', []):
            if not isinstance(fact, dict) or fact.get('current') is False:
                continue
            if any(not isinstance(fact.get(key), str) for key in ('code', 'value', 'unit', 'quote')) or not fact['value']:
                limitations.add('\u90e8\u5206\u5b57\u6bb5\u7f3a\u5c11\u539f\u503c\u6216\u539f\u6587\uff0c\u672a\u53c2\u4e0e\u5224\u5b9a\u3002')
                continue
            evidence = {'date': day.isoformat(), **{key: fact[key] for key in ('code', 'value', 'unit', 'quote')},
                        'source_job': fact.get('source_job', visit.get('source_job')),
                        'event_id': visit.get('event_id', visit.get('id')),
                        'observation': fact.get('observation')}
            identity = ('observation', evidence['observation']) if evidence['observation'] else tuple(evidence.values())
            if identity not in seen:
                seen.add(identity)
                facts.append(evidence)
    facts.sort(key=lambda item: tuple(str(item[key] or '') for key in ('date', 'code', 'value', 'unit', 'event_id', 'source_job', 'observation', 'quote')))
    return facts, sorted(dates)


def evaluate_attention(visits, as_of):
    """Return the same complete DTO for a registry list, its detail and synthetic adapters."""
    cutoff = _date(as_of)
    limitations = set()
    facts, dates = _flatten(visits, cutoff, limitations)
    items = []

    def add(kind, level, title, summary, evidence, action=None):
        identity = [[fact['date'], fact['code'], fact['value'], _unit(fact['code'], fact['unit'])] for fact in evidence]
        identifier = hashlib.sha256(json.dumps([RULES_VERSION, kind, identity], sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:24]
        if any(item['id'] == identifier for item in items):
            return
        items.append({'id': identifier, 'kind': kind, 'level': level, 'title': title, 'summary': summary,
                      'action': action or '\u8bf7\u6838\u5bf9\u539f\u62a5\u544a\u53ca\u5f53\u65f6\u60c5\u51b5\uff0c\u7531\u533b\u751f\u590d\u6838\u3002', 'evidence': evidence})

    for fact in facts:
        text = _scope(fact)
        if text is None:
            if CRITICAL.search(fact['quote']) or REFERENCE.search(fact['quote']):
                limitations.add('\u90e8\u5206\u62a5\u544a\u6807\u8bb0\u65e0\u6cd5\u660e\u786e\u5f52\u5c5e\u672c\u9879\uff0c\u9700\u6838\u5bf9\u539f\u4ef6\u3002')
            continue
        if CRITICAL.search(text):
            if _ambiguous(text):
                limitations.add('\u5371\u6025\u76f8\u5173\u539f\u6587\u542b\u5426\u5b9a\u3001\u7591\u95ee\u3001\u6761\u4ef6\u6216\u5386\u53f2\u8868\u8ff0\uff0c\u8d44\u6599\u5f85\u6838\u5bf9\u3002')
            else:
                add('critical_report', 'red', '\u62a5\u544a\u5371\u6025\u63d0\u793a\uff0c\u5904\u7406\u72b6\u6001\u5f85\u6838\u5b9e',
                    fact['date'] + '\u539f\u6587\u660e\u786e\u6807\u8bb0\u5371\u6025\u63d0\u793a\uff1b\u5904\u7406\u72b6\u6001\u672a\u77e5\uff0c\u4e0d\u4ee3\u8868\u5f53\u524d\u5371\u91cd\u3002', [fact])
        number = _number(fact['value'])
        ranges = list(REFERENCE.finditer(text)) if fact['code'] in LABELS else []
        if number is not None and len(ranges) == 1:
            low, high = Decimal(ranges[0][1]), Decimal(ranges[0][2])
            unit = _unit(fact['code'], fact['unit'])
            if low <= high and unit and _unit(fact['code'], ranges[0][3]) == unit:
                if number < low or number > high:
                    add('reference_range', 'yellow', NAMES[fact['code']] + '\u8d85\u51fa\u672c\u62a5\u544a\u53c2\u8003\u8303\u56f4',
                        fact['date'] + '\u539f\u503c' + fact['value'] + ' ' + fact['unit'] + '\uff1b\u672c\u9879\u62a5\u544a\u53c2\u8003\u8303\u56f4' + str(low) + '\u2013' + str(high) + ' ' + unit + '\u3002', [fact])
            else:
                limitations.add('\u53c2\u8003\u8303\u56f4\u7684\u5355\u4f4d\u6216\u8fb9\u754c\u9700\u6838\u5bf9\uff0c\u672a\u81ea\u52a8\u6362\u7b97\u3002')
        elif fact['code'] in LABELS and fact['code'] not in SCORES:
            limitations.add('\u90e8\u5206\u6570\u503c\u7f3a\u5c11\u53ef\u5b9a\u4f4d\u7684\u672c\u62a5\u544a\u53c2\u8003\u8303\u56f4\uff0c\u4e0d\u5957\u7528\u901a\u7528\u6b63\u5e38\u503c\u3002')
        if fact['code'] == 'infection_status':
            match = COUNT.search(text)
            recurrent = RECURRENT.search(text)
            if match or recurrent:
                if _ambiguous(text):
                    limitations.add('\u611f\u67d3\u76f8\u5173\u539f\u6587\u542b\u5426\u5b9a\u6216\u65f6\u6001\u4e0d\u660e\u8868\u8ff0\uff0c\u8d44\u6599\u5f85\u6838\u5bf9\u3002')
                elif match:
                    window, current, previous_window, previous = map(int, match.groups())
                    if 0 < window == previous_window <= 3650 and max(current, previous) <= 10000:
                        if current > previous:
                            limitations.add('\u4ecd\u9700\u6838\u5bf9\u89c2\u5bdf\u7a97\u8d77\u6b62\u548c\u72ec\u7acb\u611f\u67d3\u4e8b\u4ef6\u3002')
                            add('infection_frequency', 'orange', '\u7b49\u957f\u89c2\u5bdf\u7a97\u7684\u611f\u67d3\u8bb0\u5f55\u6b21\u6570\u589e\u52a0',
                                fact['date'] + '\u539f\u6587\u8bb0\u5f55\u8fd1' + str(window) + '\u5929' + str(current) + '\u6b21\u3001\u524d' + str(window) + '\u5929' + str(previous) + '\u6b21\uff1b\u672a\u6309\u6587\u4ef6\u6216\u4e8b\u4ef6\u6570\u8ba1\u6b21\u3002', [fact])
                    else:
                        limitations.add('\u611f\u67d3\u6b21\u6570\u7684\u89c2\u5bdf\u7a97\u6216\u6570\u503c\u4e0d\u53ef\u6bd4\uff0c\u9700\u6838\u5bf9\u3002')
                else:
                    add('recurrent_infection', 'yellow', '\u539f\u6587\u8bb0\u5f55\u53cd\u590d\u611f\u67d3',
                        fact['date'] + '\u8bb0\u5f55\u660e\u786e\u63d0\u5230\u53cd\u590d\u611f\u67d3\uff0c\u7f3a\u5c11\u53ef\u6bd4\u8f83\u6b21\u6570\uff1b\u4e0d\u63a8\u65ad\u72ec\u7acb\u53d1\u4f5c\u6570\u3002', [fact])

    def points(codes, numeric=True, observed_only=False):
        result = []
        selected_dates = sorted({fact['date'] for fact in facts if fact['code'] in codes}) if observed_only else dates
        for day in selected_dates:
            rows = [fact for fact in facts if fact['date'] == day and fact['code'] in codes]
            values = {}
            for fact in rows:
                value = _number(fact['value']) if numeric else ' '.join(unicodedata.normalize('NFKC', fact['value']).split())
                unit = _unit(fact['code'], fact['unit'])
                if numeric and (value is None or value < 0 or (fact['code'] in SCORES and value > 10)):
                    value = None
                values.setdefault((value, unit), fact)
            if len(values) == 1 and next(iter(values))[0] is not None:
                (value, unit), evidence = next(iter(values.items()))
                result.append((value, unit, evidence))
            else:
                if rows:
                    limitations.add('\u540c\u65e5\u5b57\u6bb5\u51b2\u7a81\u3001\u975e\u7cbe\u786e\u6570\u503c\u6216\u5355\u4f4d\u4e0d\u660e\uff0c\u76f8\u5173\u8d8b\u52bf\u672a\u5224\u5b9a\u3002')
                result.append(None)
        return result

    igg = points({'igg'})
    if any(fact['code'] == 'igg' for fact in facts):
        limitations.add('\u5355\u4f4d\u4e00\u81f4\u4ecd\u9700\u6838\u5bf9\u5b9e\u9a8c\u5ba4\u4e0e\u68c0\u6d4b\u65b9\u6cd5\u662f\u5426\u53ef\u6bd4\u3002')
    for count, kind, level in [(3, 'igg_rising', 'orange'), (2, 'igg_two_point', 'yellow')]:
        recent = igg[-count:]
        if len(recent) == count and all(recent) and len({point[1] for point in recent}) == 1 and recent[0][1] in ('g/L', 'mg/dL', 'g/dL') and all(a[0] < b[0] for a, b in zip(recent, recent[1:])):
            add(kind, level, 'IgG\u4e09\u4e2a\u8fde\u7eed\u8d44\u6599\u65e5\u671f\u539f\u503c\u4e0a\u5347' if count == 3 else 'IgG\u4e24\u4e2a\u8d44\u6599\u65e5\u671f\u539f\u503c\u4e0a\u5347',
                '\u622a\u81f3' + dates[-1] + '\u7684\u5f52\u6863\u539f\u503c\uff1a' + ' \u2192 '.join(point[2]['value'] for point in recent) + ' ' + recent[0][1] + '\uff1b\u4e0d\u63a8\u65ad\u75be\u75c5\u6d3b\u52a8\u5ea6\u3002', [point[2] for point in recent])
            break
    for code, name in SCORES.items():
        recent = points({code})[-2:]
        if len(recent) == 2 and all(recent) and recent[0][1] == recent[1][1] == '\u5206' and recent[0][0] != recent[1][0]:
            add('score_change', 'yellow', name + '\u8bb0\u5f55\u53d8\u5316',
                recent[0][2]['date'] + '\u81f3' + recent[1][2]['date'] + '\uff1a' + str(recent[0][0]) + '\u2192' + str(recent[1][0]) + '\u5206\uff1b\u4ec5\u4e3a\u5355\u9879\u539f\u503c\u53d8\u5316\u3002', [point[2] for point in recent])
    recent = points({'medications', 'prescription'}, numeric=False, observed_only=True)[-2:]
    if len(recent) == 2 and all(recent) and recent[0][0] != recent[1][0]:
        add('medication_change', 'yellow', '\u7528\u836f\u8bb0\u5f55\u6587\u5b57\u53d8\u5316',
            recent[0][2]['date'] + '\u4e0e' + recent[1][2]['date'] + '\u7684\u7528\u836f\u539f\u6587\u4e0d\u540c\uff1b\u4e0d\u63a8\u65ad\u5b9e\u9645\u670d\u836f\u3001\u505c\u836f\u6216\u7597\u6548\u3002', [point[2] for point in recent])
    if not items:
        limitations.add('\u672a\u8bc6\u522b\u5230\u5173\u6ce8\u4fe1\u53f7\uff1b\u8d44\u6599\u4e0d\u8db3\u4e0d\u7b49\u4e8e\u6b63\u5e38\u3002')
    if dates:
        limitations.add('\u5224\u5b9a\u4ec5\u57fa\u4e8e\u5df2\u5f52\u6863\u8bb0\u5f55\uff0c\u6700\u65b0\u8d44\u6599\u65e5\u671f\u4e3a' + dates[-1] + '\uff1b\u4e0d\u8868\u793a\u5f53\u524d\u72b6\u6001\u3002')
    items.sort(key=lambda item: (-LEVELS[item['level']], item['kind'], item['id']))
    return {'rules_version': RULES_VERSION, 'as_of': cutoff.isoformat(),
            'level': items[0]['level'] if items else 'gray', 'items': items, 'limitations': sorted(limitations)}
