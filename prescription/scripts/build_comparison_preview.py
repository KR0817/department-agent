"""Build isolated synthetic comparison fixtures; never load clinical inputs."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from build_network_3d_preview import build as build_network

PATTERN = r'(<script id="(?:dashboard-data|supplement-data)" type="application/json">)(.*?)(</script>)'


def transform(page):
    def replace(match):
        payload = json.loads(match[2])
        assert payload['provenance']['synthetic_mode'] is True
        if match[1].startswith('<script id="dashboard-data"'):
            research = payload['research']
            base = research['cohorts'][0]
            research['cohorts'].append({**base, 'group': 'sjd_strict',
                'label': '\u5e72\u71e5\u75c5', 'patients': '40'})
            originals = list(research['nodes'])
            chosen = [row for index, row in enumerate(originals) if index not in (1, 17)]
            members = {row['item_name']: {(offset + index * 3) % 40
                for offset in range(32 - index % 9)} for index, row in enumerate(chosen)}
            nodes = []
            for row in reversed(chosen):
                count = len(members[row['item_name']])
                nodes.append({**row, 'group': 'sjd_strict', 'patients': '40',
                    'exposed_patients': str(count), 'prevalence': str(count / 40)})
            edges = []
            for row in list(research['edges']):
                if row['item_1'] not in members or row['item_2'] not in members:
                    continue
                a, b = members[row['item_1']], members[row['item_2']]
                count = len(a & b)
                edges.append({**row, 'group': 'sjd_strict', 'patients': '40',
                    'cooccurrence_patients': str(count), 'support': str(count / 40),
                    'cosine_similarity': str(count / math.sqrt(len(a) * len(b))),
                    'lift': '' if row['lift'] == '' else str(count * 40 / (len(a) * len(b)))})
            research['nodes'].extend(nodes)
            research['edges'].extend(edges)
        encoded = json.dumps(payload, ensure_ascii=True).replace('<', '\\u003c')
        return match[1] + encoded + match[3]
    result = re.sub(PATTERN, replace, page, flags=re.S)
    return result.replace('Each source has 18 disclosed network nodes and 130 fabricated edges.',
        'The primary fixture has two strict cohorts with different node subsets; the supplement has one.')


def build(output):
    build_network(output)
    names = ['refined.html', 'empty-network.html', 'long-network.html']
    for name in names:
        path = output / name
        path.write_text(transform(path.read_text(encoding='utf-8')), encoding='utf-8')
    # Use the fully enhanced page so edge and group empty states are independent.
    enhanced = (output / 'refined.html').read_text(encoding='utf-8')
    def group_variant(mode):
        def replace(match):
            payload = json.loads(match[2])
            assert payload['provenance']['synthetic_mode'] is True
            if mode == 'empty-matrix':
                payload['groups'] = []
            else:
                payload['groups'][-1]['patients'] = ''
            return match[1] + json.dumps(payload, ensure_ascii=True).replace('<', '\\u003c') + match[3]
        return re.sub(PATTERN, replace, enhanced, flags=re.S)
    for mode in ['empty-matrix', 'missing-count']:
        (output / (mode + '.html')).write_text(group_variant(mode), encoding='utf-8')
    path = output / 'preview-manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['purpose'] = 'synthetic-comparison-workspace-validation'
    manifest['network_fixture'] = {}
    for match in re.finditer(PATTERN, enhanced, flags=re.S):
        data = json.loads(match[2])
        source = 'primary' if match[1].startswith('<script id="dashboard-data"') else 'supplement'
        manifest['network_fixture'][source] = {cohort['group']: {
            'nodes': sum(row['group'] == cohort['group'] for row in data['research']['nodes']),
            'edges': sum(row['group'] == cohort['group'] for row in data['research']['edges'])}
            for cohort in data['research']['cohorts']}
    manifest['fixture_changes'].extend(['Second primary strict cohort with reversed subset and denominator 40',
        'One-cohort supplement; empty and missing-count group matrix variants'])
    manifest['files'] = {file.name: hashlib.sha256(file.read_bytes()).hexdigest()
                         for file in sorted(output.glob('*.html'))}
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'purpose': manifest['purpose'], 'files': manifest['files']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
