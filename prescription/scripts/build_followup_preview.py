"""Create explicitly synthetic follow-up UI fixtures without clinical inputs."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from build_ui_refactor_preview import build

PATTERN = r'(<script id="(?:dashboard-data|supplement-data)" type="application/json">)(.*?)(</script>)'


def transform(page, kind):
    count = 0
    def replace(match):
        nonlocal count
        payload = json.loads(match[2])
        assert payload['provenance']['synthetic_mode'] is True
        count += 1
        if kind == 'empty':
            for key in ('changes', 'yearChanges', 'longitudinal'):
                payload[key] = []
        else:
            payload['longitudinal'] = [dict(group=row['code'], stratum_type='overall', stratum='all',
                repeat_patients=row['patients'], transitions=str(int(row['patients']) * 3),
                median_patient_jaccard='0' if row['code'] == 'ra__as' else '.75')
                for row in payload['groups'] if row['code'] != 'sjd']
            for key in ('changes', 'yearChanges'):
                expanded = []
                for row in payload[key]:
                    for index, item in enumerate(('\u9ec4\u82aa', '\u767d\u828d', '\u832f\u82d3')):
                        if index == 2 and row['change_type'] == 'removal':
                            continue
                        value = deepcopy(row)
                        value['item_name'] = item
                        if index == 1:
                            for field in list(value):
                                if 'dose' in field:
                                    value[field] = ''
                        expanded.append(value)
                payload[key] = expanded
        if kind == 'long-label':
            for key in ('changes', 'yearChanges'):
                for row in payload[key]:
                    if row['item_name'] == '\u9ec4\u82aa':
                        row['item_name'] += '\uff08\u957f\u540d\u79f0\u6392\u7248\u6d4b\u8bd5\uff1a\u5408\u6210\u836f\u5473\u6807\u7b7e\uff09'
        encoded = json.dumps(payload, ensure_ascii=True).replace('<', '\\u003c')
        return match[1] + encoded + match[3]
    result = re.sub(PATTERN, replace, page, flags=re.S)
    assert count == 2
    return result


def build_cases(output):
    manifest = build(output, 'dense')
    base = (output / 'refined.html').read_text(encoding='utf-8')
    for name, kind in (('refined.html', 'default'), ('empty.html', 'empty'), ('long-label.html', 'long-label')):
        (output / name).write_text(transform(base, kind), encoding='utf-8')
    manifest['purpose'] = 'synthetic-followup-ui-validation'
    manifest['fixture_changes'] = ['Fabricated longitudinal group summaries including zero Jaccard',
        'Three display drug labels with missing dose and missing removal cases',
        '2021 unavailable annual changes', 'Empty and long-label fixtures']
    manifest['files'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in sorted(output.glob('*.html'))}
    (output / 'preview-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build_cases(parser.parse_args().output)
