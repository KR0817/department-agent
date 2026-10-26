"""Build a private exact-original-prescription teaching workspace or pure fixture."""
import argparse
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mingyirx.clinical_server import STATIC_NAMES
from mingyirx.dashboard_clinical import render_clinical_workspace
from mingyirx.dashboard_exact_rx import render_exact_rx
from mingyirx.exact_rx_teaching import (HEADER, SCHEMA, canonical, digest, read_source,
    select_episodes, verify_exact)
from mingyirx.inheritance import assert_output_allowed


def create_fixture(path: Path, rules: dict):
    """Create invented rows including duplicates and preserved decimal strings."""
    diagnoses = ['\u7c7b\u98ce\u6e7f\u5173\u8282\u708e', '\u5e72\u71e5\u7efc\u5408\u5f81',
                 '\u5f3a\u76f4\u6027\u810a\u67f1\u708e',
                 '\u7c7b\u98ce\u6e7f\u5173\u8282\u708e;\u5e72\u71e5\u7efc\u5408\u5f81', 'Synthetic other']
    with path.open('w', encoding='gb18030', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADER)
        for subject, diagnosis in enumerate(diagnoses):
            for visit in range(3):
                names = rules['profiles'][(subject+visit) % len(rules['profiles'])]['cues'][:5]
                names = [*names, rules['profiles'][subject]['cues'][0]]
                for name in names:
                    row = [''] * 17
                    row[2:5] = [f'SYN-CLINIC-{subject}-{visit}', f'SYN-SUBJECT-{subject}',
                                (datetime(2000, 1, 1)+timedelta(days=visit*14)).strftime('%Y/%m/%d %H:%M:%S')]
                    row[8] = diagnosis
                    row[11:] = [name, '98.0000', '7.0', 'QD', ['10.00', '12.0', '9'][visit], 'g']
                    writer.writerow(row)


def build(output: Path, aggregate_site: Path, source: Path | None = None):
    original = source is not None
    assert_output_allowed({'synthetic': not original, 'local_authorization': original,
                           'deidentified': True}, output)
    base = aggregate_site.resolve(strict=True)
    if not all((base / name).is_file() for name in ('aggregate.html', 'inheritance.html')):
        raise ValueError('WORKSPACE_BASE_INCOMPLETE')
    rules_path = ROOT / 'configs/exact_rx_teaching_rules.json'
    rules = json.loads(rules_path.read_text('utf-8'))
    config = json.loads((ROOT / 'configs/local_gb18030.template.json').read_text('utf-8'))
    output.mkdir(parents=True, exist_ok=False)
    if original:
        expected = config['expected_input_sha256'].get(source.name)
        if not expected:
            raise ValueError('SOURCE_NOT_PINNED')
    else:
        source = output / 'synthetic-prescriptions.csv'
        create_fixture(source, rules)
        expected = digest(source)
    groups, intake = read_source(source, expected)
    excluded = '|'.join(config['item_eligibility']['excluded_name_patterns']
                        + config['item_eligibility']['excluded_exact_names'])
    episodes = select_episodes(groups, rules, excluded)
    if not episodes:
        raise ValueError('NO_COMPLETE_ADJACENT_WINDOW')
    verification = verify_exact(source, episodes, expected)
    # No raw linkage keys, dates, diagnosis strings or maps leave read_source.
    del groups
    bundle = {'schema_version': SCHEMA,
        'mode': 'original_rx_simulated_clinical' if original else 'synthetic_software_fixture',
        'source_sha256': expected.lower(), 'rule_version': rules['version'],
        'rule_sha256': digest(rules_path), 'clinical_validation': False,
        'episodes': episodes, 'verification': verification}
    (output / 'exact-rx-bundle.json').write_bytes(canonical(bundle))
    site = output / 'site'
    site.mkdir()
    preserved = {}
    for file in sorted(base.iterdir()):
        if file.is_file() and file.name in STATIC_NAMES and file.name not in ('index.html', 'exact-rx.html'):
            shutil.copyfile(file, site / file.name)
            if digest(file) != digest(site / file.name):
                raise ValueError('INCUMBENT_SITE_COPY_MISMATCH')
            preserved[file.name] = digest(file)
    provenance_path = base / 'teaching-provenance.json'
    provenance = json.loads(provenance_path.read_text('utf-8')) if provenance_path.exists() else None
    (site / 'index.html').write_text(render_clinical_workspace(synthetic_preview=not original,
        teaching_provenance=provenance, exact_rx_teaching=True), encoding='utf-8', newline='\n')
    (site / 'exact-rx.html').write_text(render_exact_rx(bundle), encoding='utf-8', newline='\n')
    receipt = {'schema_version': SCHEMA, 'mode': bundle['mode'],
        'source_sha256': expected.lower(), 'rule_sha256': digest(rules_path),
        'case_count': len(episodes), 'visit_count': sum(len(e['visits']) for e in episodes),
        'pair_count': sum(len(e['visits'])-1 for e in episodes),
        'simulation_profile_transitions': sum(a['simulation']['profile_id'] != b['simulation']['profile_id']
            for e in episodes for a,b in zip(e['visits'], e['visits'][1:])),
        'intake': intake, 'verification': verification, 'incumbent_files': preserved,
        'site_files': {p.name: digest(p) for p in sorted(site.iterdir())},
        'raw_identity_fields_exported': False, 'external_transfer': False,
        'independent_clinical_reference': False, 'clinical_validation': False}
    (output / 'build-receipt.json').write_bytes(canonical(receipt))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--aggregate-site', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--input', type=Path)
    mode.add_argument('--synthetic-fixture', action='store_true')
    args = parser.parse_args()
    result = build(args.output, args.aggregate_site, args.input)
    print(json.dumps({key: result[key] for key in ('mode', 'case_count', 'visit_count',
        'pair_count', 'simulation_profile_transitions', 'verification')}, indent=2))
