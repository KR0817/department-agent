"""Build explicitly synthetic integration fixtures without clinical inputs."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from io import StringIO
from copy import deepcopy
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1] / 'prescription'
for folder in ('src', 'scripts', 'tests'):
    sys.path.insert(0, str(ROOT / folder))

from build_comparison_preview import build as build_comparison
from build_exact_rx_workspace import build as build_exact
from mingyirx.dashboard_clinical import render_clinical_workspace
from mingyirx.dashboard_inheritance import render_inheritance
from mingyirx.inheritance import load_bundle, build_view
from test_dashboard_clinical import teaching_sidecar, candidates

PATTERN = re.compile(r'(<script id="(dashboard-data|supplement-data)" type="application/json">)(.*?)(</script>)', re.S)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def enrich(payload):
    """Add fabricated rows to exercise previously empty display branches."""
    assert payload['provenance']['synthetic_mode'] is True
    payload = deepcopy(payload)
    research = payload['research']
    for key in ('matched', 'sensitivity', 'modes', 'thresholds', 'doseAudit'):
        research[key] = []
    for cohort in research['cohorts']:
        group, patients = cohort['group'], cohort['patients']
        research['matched'].append(dict(group=group, patients=patients, matched_transitions=patients,
            observed_patient_median_jaccard='.75', observed_bootstrap_ci95_low='.65', observed_bootstrap_ci95_high='.85',
            matched_between_patient_median_jaccard='.40', matched_between_bootstrap_ci95_low='.30', matched_between_bootstrap_ci95_high='.50',
            within_minus_between_median='.35', within_minus_between_bootstrap_ci95_low='.20', within_minus_between_bootstrap_ci95_high='.45',
            empirical_one_sided_bh_fdr='.05'))
        research['sensitivity'].append(dict(group=group, analysis='SYNTHETIC_DISPLAY_ONLY', patients=patients,
            transitions=patients, observed_patient_median_jaccard='.75', matched_between_patient_median_jaccard='.40',
            within_minus_between_median='.35', within_minus_between_bootstrap_ci95_low='.20', within_minus_between_bootstrap_ci95_high='.45'))
        for mode in ('exact_repeat', 'dose_only', 'composition_only', 'composition_and_dose'):
            research['modes'].append(dict(group=group, mode=mode, dose_resolved_patients=patients,
                dose_resolved_transitions=patients, mean_patient_proportion='.25'))
        nodes = [r for r in research['nodes'] if r['group'] == group]
        edges = [r for r in research['edges'] if r['group'] == group]
        research['thresholds'].append(dict(group=group, node_prevalence_threshold='.1', edge_cosine_threshold='.2',
            stable_nodes=str(len(nodes)), edges=str(len(edges)), node_retention_vs_primary='1',
            edge_retention_vs_primary='1', primary_setting='True'))
        research['doseAudit'].append(dict(group=group, patients=patients, visits=str(int(patients)*3),
            patients_with_conflict='0', visits_with_conflict='0', visit_item_conflicts='0', patients_with_conflict_pct='0'))
    research['normalization'] = [dict(dictionary_version='SYNTHETIC_NO_MAPPING', dictionary_entries='0', dictionary_sha256='0'*64)]
    names = list(dict.fromkeys(r['item_name'] for r in payload['items']))
    research['usage'] = [dict(item_name=name, total_usage_visits=str(200-i*5)) for i, name in enumerate(names)]
    first = payload['groups'][0]
    combo = deepcopy(payload['combinations'][0])
    combo.update(combination=' | '.join(names[:3]), combination_size='3')
    payload['combinations'].append(combo)
    base_items = [r for r in payload['items'] if r['group'] == first['code'] and r['stratum_type']=='overall']
    existing = [r for r in payload['summaries'] if r['group']==first['code'] and r['stratum_type']=='sex']
    if existing:
        for row in base_items:
            copy = deepcopy(row)
            copy.update(stratum_type='sex', stratum='female', group_patients='20', exposed_patients='10', prevalence='.5')
            payload['items'].append(copy)
    payload['summaries'].append(dict(group=first['code'], stratum_type='age', stratum='40-49', stratum_label='40-49', patients='20', repeat_patients='20'))
    for row in base_items:
        copy = deepcopy(row)
        copy.update(stratum_type='age', stratum='40-49', group_patients='20', exposed_patients='10', prevalence='.5')
        payload['items'].append(copy)
    payload['provenance']['dataset_id'] = 'department-full-qa-synthetic-only'
    payload['provenance']['analysis_version'] = 'fabricated-display-values-not-computed-estimates'
    return payload


def csv_file(path, rows):
    assert rows
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def report_page(retention, literature):
    """A functional synthetic report substitute; not original report fidelity."""
    sections = []
    for index, disease in enumerate(('sjd', 'ra')):
        row = next(r for r in retention if r['group']==disease)
        title = 'Synthetic SjD' if disease == 'sjd' else 'Synthetic RA'
        sections.append(f'<section id="evidence-{disease}"'+(' hidden' if index else '')+f'><h2>{title}</h2>'
            '<p>Fabricated literature-versus-pattern test. No actual paper, clinician interpretation or efficacy claim is represented.</p>'
            '<article><h3>Pattern and literature comparison</h3><div class="columns"><div><h4>Document fixture</h4>'
            '<p>A fictional document label tests the source/details panel. It is not a bibliographic citation.</p></div>'
            f'<div><h4>Fabricated prescription retention</h4><p>{row["retained_patients"]} of {row["at_risk_patients"]} invented subjects retained the fixture medicine set.</p></div></div>'
            '<details><summary>Evidence, denominator and test scope</summary><p>All counts were deliberately authored for interface coverage. No inferential analysis was run.</p>'
            '<a href="source-ledger.json">Fixture source ledger</a></details></article></section>')
    switch = ''.join(f'<label><input type="radio" name="evidence-disease" value="{d}"'+(' checked' if i==0 else '')+f'> Synthetic {d.upper()}</label>' for i,d in enumerate(('sjd','ra')))
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Synthetic literature report QA</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f5f7f0;color:#203f32;font:16px/1.6 system-ui,sans-serif}main{max-width:1100px;margin:auto;padding:24px}h1{font-size:30px}.notice,article,details{padding:16px;border:1px solid #bbcebd;margin:16px 0;background:white}.notice{background:#fff1c8}.columns{display:grid;grid-template-columns:1fr 1fr;gap:20px}.disease-switch{display:flex;gap:20px;flex-wrap:wrap}a{color:#205e48}summary,input{cursor:pointer}[hidden]{display:none!important}@media(max-width:600px){.columns{grid-template-columns:1fr}main{padding:14px}}
    </style></head><body><main><p class="notice">SYNTHETIC QA SUBSTITUTE: report routing, disease switching, details and downloads only. Original report prose, citations and visual fidelity are not exercised by this substitute.</p><a href="index.html">Back to clinical workspace</a> | <a href="aggregate.html">Aggregate workbench</a><h1>Literature and prescription report fixture</h1><section id="formula-evidence"><div class="disease-switch">'''+switch+'</div>'+''.join(sections)+'''</section><details><summary>Earlier report and methods fixture</summary><p>This is a deliberately authored synthetic test report; no historical scientific evidence is copied.</p><a href="analysis-report.md">Fixture construction and limits</a></details><nav><a href="conditional_retention.csv" download>Conditional retention CSV</a> | <a href="disease-change-results.csv" download>Disease changes CSV</a> | <a href="literature-analysis-results.csv" download>Literature comparison fixture CSV</a></nav></main><script id="evidence-switch-script">(()=>{const root=document.getElementById('formula-evidence');for(const input of root.querySelectorAll('input[name="evidence-disease"]'))input.addEventListener('change',()=>{for(const group of ['sjd','ra'])document.getElementById('evidence-'+group).hidden=input.value!==group;});})();</script></body></html>'''


def _build_fixture(output):
    output.mkdir(parents=True, exist_ok=False)
    comparison = output / 'comparison-fixtures'
    with redirect_stdout(StringIO()):
        build_comparison(comparison)
    payloads = {}
    def replace(match):
        payload = enrich(json.loads(match[3]))
        payloads['primary' if match[2]=='dashboard-data' else 'supplement'] = payload
        return match[1]+json.dumps(payload,ensure_ascii=True).replace('<','\\u003c')+match[4]
    aggregate = PATTERN.sub(replace, (comparison/'refined.html').read_text(encoding='utf-8'))
    assert set(payloads)=={'primary','supplement'}
    notice = '<aside class="policy-note"><b>SYNTHETIC QA ONLY</b><p>All inputs and numerical estimates are fabricated display fixtures, not clinical findings.</p><a href="research-report.html">Synthetic report fixture</a> | <a href="supplement.html">Supplement fixture</a> | <a href="analysis-report.md">Fixture report</a></aside>'
    aggregate = aggregate.replace('<main class="main" id="main-workbench" tabindex="-1">','<main class="main" id="main-workbench" tabindex="-1">'+notice,1)
    base = output/'base'
    base.mkdir()
    (base/'aggregate.html').write_text(aggregate,encoding='utf-8')
    bundle = load_bundle(ROOT/'data/synthetic/inheritance_cases.json')
    assert bundle['synthetic'] is True
    (base/'inheritance.html').write_text(render_inheritance(bundle,build_view(bundle)),encoding='utf-8')
    provenance = teaching_sidecar()
    provenance['fixture_scope'] = 'Synthetic teaching-anchor display fixture; not an aggregate-derived patient linkage.'
    (base/'teaching-provenance.json').write_text(json.dumps(provenance,ensure_ascii=True,indent=2),encoding='utf-8')
    receipt = build_exact(output/'workspace',base)
    assert receipt['mode']=='synthetic_software_fixture'
    site = output/'workspace/site'
    supplement = aggregate.replace('const defaultSource="primary"','const defaultSource="supplement"',1)
    assert supplement != aggregate
    (site/'supplement.html').write_text(supplement,encoding='utf-8')
    retention = [dict(synthetic=True,group=d,unit='Synthetic set A',at_risk_patients=12,retained_patients=9,patient_equal_retention='.75',scope='fabricated_display_fixture') for d in ('sjd','ra')]
    literature = [dict(synthetic=True,group=d,document_id='FICTIONAL_QA_DOCUMENT',comparison='fixture_pattern',source_status='NO_REAL_REFERENCE',scope='fabricated_display_fixture') for d in ('sjd','ra')]
    csv_file(site/'conditional_retention.csv',retention)
    csv_file(site/'disease-change-results.csv',[dict(synthetic=True,source=key,**row) for key,payload in payloads.items() for row in payload['changes']])
    csv_file(site/'literature-analysis-results.csv',literature)
    (site/'research-report.html').write_text(report_page(retention,literature),encoding='utf-8')
    (site/'source-ledger.json').write_text(json.dumps({'synthetic':True,'raw_patient_data_read':False,'fixture_sources':['tests/test_original_interactions.py','scripts/build_ui_refactor_preview.py','scripts/build_comparison_preview.py','data/synthetic/inheritance_cases.json','scripts/build_exact_rx_workspace.py','tests/test_dashboard_clinical.py'],'fictional_report_documents':['FICTIONAL_QA_DOCUMENT'],'clinical_validation':False},indent=2),encoding='utf-8')
    (site/'source-correction.json').write_text(json.dumps({'synthetic':True,'all_sources_setting':'fabricated_outpatient_fixture','primary_denominator':'source_independent','cross_source_union':False,'clinical_data_loaded':False},indent=2),encoding='utf-8')
    (site/'analysis-report.md').write_text('# Synthetic full integration fixture\n\nAll source observations, counts, doses and display estimates are fabricated. No original outpatient dataset is read.\n\nPrimary and supplemental sources remain independent. The aggregate, exact-prescription, inheritance and clinical-shell renderers are the incumbent production renderers. The independent supplemental page reuses the complete same aggregate renderer with supplemental default.\n\nThe report page and three report CSV downloads are functional synthetic substitutes. They exercise disease switching, details, local links and downloads, but do not establish original report visual fidelity or clinical claims. Inferential display values were authored, not statistically estimated.\n\nDynamic saved-collection HTML is produced by the incumbent LocalWorkspace service and is not a static file. Import, review, commit and resume must be tested through that service using the provided synthetic fixtures.\n',encoding='utf-8')
    (site/'robots.txt').write_text('User-agent: *\nDisallow: /\n',encoding='ascii')
    fixture = candidates()
    (output/'synthetic-candidate-records.json').write_text(json.dumps(fixture,ensure_ascii=True,indent=2),encoding='utf-8')
    text='\n\n'.join('\n'.join(f'{key}: {record[key]}' for key in ('subject_code','episode_code','physician_code','visit_code','date','sequence','condition','symptoms','tongue','pulse','syndrome','principle','prescription')) for record in fixture['records'])
    (output/'synthetic-upload.txt').write_text(text+'\n',encoding='utf-8')
    manifest={'synthetic':True,'original_patient_records_read':False,'site':str(site.resolve()),'production_renderers':['clinical shell','aggregate','inheritance','exact prescriptions'],'substitute_surfaces':['research-report.html','conditional_retention.csv','disease-change-results.csv','literature-analysis-results.csv','source-ledger.json','source-correction.json','analysis-report.md'],'not_established':['Original legacy report visual fidelity','Clinical validity','Live local OCR capability'],'files':{p.name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(site.iterdir())},'exact_fixture':{'mode':receipt['mode'],'case_count':receipt['case_count'],'visit_count':receipt['visit_count'],'pair_count':receipt['pair_count']},'source_groups':{key:len(value['groups']) for key,value in payloads.items()},'strict_cohorts':{key:len(value['research']['cohorts']) for key,value in payloads.items()}}
    assert len(manifest['files'])==14
    (output/'qa-site-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return site


def build(output: Path | None = None) -> Path:
    """Build all fourteen public demo assets from invented inputs only.

    Output and intermediate folders must be new children of the ignored local
    prescription work directory. Existing output is never silently replaced.
    """
    output = Path(output) if output is not None else ROOT / 'work/demo-site'
    output = output.absolute()
    work_root = (ROOT / 'work').resolve()
    if output.resolve() == work_root or not output.resolve().is_relative_to(work_root):
        raise ValueError('DEMO_OUTPUT_REQUIRES_IGNORED_WORK_DIRECTORY')
    staging = output.with_name(output.name + '-build')
    if output.exists() or staging.exists():
        raise ValueError('DEMO_OUTPUT_ALREADY_EXISTS')
    site = _build_fixture(staging)
    shutil.copytree(site, output)
    from mingyirx.clinical_server import STATIC_NAMES
    if {path.name for path in output.iterdir()} != STATIC_NAMES:
        raise ValueError('DEMO_STATIC_ASSET_SET_MISMATCH')
    for path in output.iterdir():
        if sha(path) != sha(site / path.name):
            raise ValueError('DEMO_STATIC_COPY_MISMATCH')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    site = build(parser.parse_args().output)
    print(json.dumps({'synthetic': True, 'site': str(site), 'assets': 14,
                      'clinical_validation': False}))
