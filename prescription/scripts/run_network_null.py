"""Verify a baseline manifest and run a separate fixed-margin network analysis."""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from mingyirx.io import file_sha256
from mingyirx.network_null import fixed_margin_network
from mingyirx.pipeline import _write_csv, validate_pipeline
from mingyirx.privacy import scan_public_outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--thin-sweeps', type=int, default=2)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output directory exists')
    manifest = json.loads((args.baseline/'run_manifest.json').read_text(encoding='utf-8'))
    if manifest['gate'] == 'BLOCK':
        raise ValueError('Baseline is blocked')
    config = Path(manifest['configuration']['absolute_path'])
    if file_sha256(config) != manifest['configuration']['sha256']:
        raise ValueError('Configuration hash mismatch')
    for name, digest in manifest['artifacts'].items():
        if (args.baseline/name).resolve().parent != args.baseline.resolve():
            raise ValueError('Invalid artifact path')
        if file_sha256(args.baseline/name) != digest:
            raise ValueError('Baseline artifact hash mismatch')
    inputs = [Path(item['absolute_path']) for item in manifest['inputs']]
    for path, item in zip(inputs, manifest['inputs']):
        if file_sha256(path) != item['sha256']:
            raise ValueError('Source hash mismatch')
    context = validate_pipeline(config, inputs)
    grouped = defaultdict(list)
    for _, visits in sorted(context.visit_result.visits_by_patient.items()):
        grouped[visits[0].group].append(set(visits[0].items))
    rows, diagnostics = [], []
    for index, (group, prescriptions) in enumerate(sorted(grouped.items())):
        cfg = context.config
        edges, diag = fixed_margin_network(prescriptions, group, cfg.min_public_n,
                                           cfg.core_prevalence, cfg.network_analysis.stability_probability,
                                           cfg.network_analysis.primary_cosine, seed=20260909+100*index,
                                           thin_sweeps=args.thin_sweeps)
        rows.extend(edges)
        diagnostics.append(diag)
        print(json.dumps({'group':group,'sampling':diag['status']}), flush=True)
    # Verify that the existing primary graph is a strict projection of this family.
    with (args.baseline/'network_edges.csv').open(encoding='utf-8',newline='') as handle:
        prior = {(r['group'],r['item_1'],r['item_2']):int(r['cooccurrence_patients']) for r in csv.DictReader(handle)}
    projected = {(r['group'],r['item_1'],r['item_2']):r['observed_cooccurrence_patients'] for r in rows if r['primary_network_edge']}
    if prior != projected:
        raise ValueError('Primary network membership or counts differ')
    args.output.mkdir(parents=True)
    table = args.output/'network_null_edges.csv'
    fields = list(rows[0]) if rows else ['group','item_1','item_2','mc_upper_tail_p','mc_bh_q']
    _write_csv(table, fields, rows)
    (args.output/'sampling_diagnostics.json').write_text(json.dumps(diagnostics,indent=2),encoding='utf-8')
    for name, digest in manifest['artifacts'].items():
        if file_sha256(args.baseline/name) != digest:
            raise ValueError('Baseline artifact changed during analysis')
    provenance = {'analysis':'network-null-v1','cohort_version':cfg.cohort_version,'dataset_id':cfg.dataset_id,
                  'decision_basis':'user_finalized_column_b','config_sha256':file_sha256(config),
                  'dictionary_sha256':cfg.item_normalization.dictionary_sha256,
                  'input_sha256':[item.sha256 for item in context.read_result.source_files],
                  'module_sha256':file_sha256(Path(__file__).resolve().parents[1]/'src/mingyirx/network_null.py'),
                  'table_sha256':file_sha256(table),'primary_graph_projection':'PASS',
                  'baseline_artifacts_unchanged':len(manifest['artifacts']),
                  'min_public_n':cfg.min_public_n,'gate':'PASS_WITH_WARNINGS',
                  'inference':'EXPLORATORY_CORRELATED_MONTE_CARLO_NO_CONFIRMED_SYNERGY'}
    (args.output/'analysis_provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    scan=scan_public_outputs(args.output)
    if scan.issues:
        raise ValueError('Privacy scan failed')
    print(json.dumps({'gate':'PASS_WITH_WARNINGS','disclosed_edges':len(rows),'privacy_issues':0}),flush=True)


if __name__ == '__main__':
    main()
