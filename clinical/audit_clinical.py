"""Read-only consistency audit inside the synthetic service runtime."""
import json
import sqlite3
import clinical

con = sqlite3.connect('/data/jobs.sqlite')
rows = con.execute('SELECT sha,state FROM jobs').fetchall()
unreviewed = {sha for sha, state in rows if state != 'published'}
resources = {kind: clinical.search(kind, {'_count': '200'}) for kind in
             ('Patient', 'Encounter', 'Observation', 'Provenance', 'Task', 'Basic')}
checks = {}
for kind, items in resources.items():
    identifiers = [i['value'] for r in items for i in r.get('identifier', []) if i.get('system') == clinical.SYSTEM]
    checks[kind + '_identifiers_unique'] = len(identifiers) == len(set(identifiers))
obs = resources['Observation']
checks['unreviewed_sources_absent_from_observations'] = not any(
    e.get('valueString') in unreviewed for r in obs for e in r.get('extension', [])
    if e['url'] == clinical.SYSTEM + '/source-sha256')
targets = {t.get('reference') for p in resources['Provenance'] for t in p['target']}
checks['every_observation_has_provenance'] = all('Observation/' + r['id'] in targets for r in obs)
patients = {'Patient/' + r['id'] for r in resources['Patient']}
encounters = {'Encounter/' + r['id'] for r in resources['Encounter']}
checks['observation_references_resolve'] = all(r['subject']['reference'] in patients and r['encounter']['reference'] in encounters for r in obs)
checks['task_patients_resolve'] = all(r['for']['reference'] in patients for r in resources['Task'])
checks['automatic_followup_completion_has_encounter'] = all(
    any(o.get('valueReference', {}).get('reference') in encounters for o in t.get('output', []))
    for t in resources['Task'] if t['status'] == 'completed' and
    any(c.get('code') == 'visit-based-followup-v1' for c in t.get('code', {}).get('coding', [])))
print(json.dumps({'data_origin': 'simulated', 'counts': {k: len(v) for k, v in resources.items()},
                  'checks': checks, 'passed': all(checks.values())}, indent=2))
