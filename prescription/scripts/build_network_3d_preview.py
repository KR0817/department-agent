"""Create isolated synthetic 3D network fixtures; never load clinical inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from build_followup_preview import build_cases


def variant(page, mode):
    def replace(match):
        payload = json.loads(match[2])
        assert payload['provenance']['synthetic_mode'] is True
        if mode == 'empty':
            payload['research']['nodes'] = []
            payload['research']['edges'] = []
        else:
            name = payload['research']['nodes'][0]['item_name']
            label = name + '\uff08\u957f\u836f\u540d\u5408\u6210\u6392\u7248\u6d4b\u8bd5\uff09'
            def rename(value):
                if isinstance(value, str):
                    return label if value == name else value
                if isinstance(value, list):
                    return [rename(item) for item in value]
                if isinstance(value, dict):
                    return {key: rename(item) for key, item in value.items()}
                return value
            payload = rename(payload)
        return match[1] + json.dumps(payload, ensure_ascii=True).replace('<', '\\u003c') + match[3]
    return re.sub(r'(<script id="(?:dashboard-data|supplement-data)" type="application/json">)(.*?)(</script>)', replace, page, flags=re.S)


def build(output):
    build_cases(output)
    page = (output / 'refined.html').read_text(encoding='utf-8')
    for name, mode in [('empty-network.html', 'empty'), ('long-network.html', 'long')]:
        (output / name).write_text(variant(page, mode), encoding='utf-8')
    path = output / 'preview-manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['purpose'] = 'synthetic-network-3d-validation'
    manifest['fixture_changes'].extend(['Empty network', 'Long medication label throughout all synthetic views'])
    manifest['files'] = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(output.glob('*.html'))}
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'purpose': manifest['purpose'], 'synthetic_mode': True, 'files': manifest['files']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
