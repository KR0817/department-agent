"""Business patient identities and immutable upload selections; no demo enrollment."""
import datetime as dt
import json
import re
import unicodedata

CONTEXT_CODES = ('medications', 'inpatient_exams', 'infection_status', 'comorbidities', 'baseline_exams')
PATIENT_ID = re.compile(r'[A-Za-z0-9_-]{3,64}\Z')


class RegistryError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def initialize(con):
    con.execute('''CREATE TABLE IF NOT EXISTS patient_registry (
        patient_id TEXT PRIMARY KEY, name TEXT NOT NULL, sex TEXT NOT NULL,
        birth_date TEXT, created_at TEXT NOT NULL, actor TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS job_patient_association (
        job_id TEXT PRIMARY KEY REFERENCES jobs(id), patient_id TEXT NOT NULL,
        name TEXT NOT NULL, source TEXT NOT NULL, actor TEXT NOT NULL, selected_at TEXT NOT NULL)''')
    con.execute('CREATE INDEX IF NOT EXISTS association_patient ON job_patient_association(patient_id)')


def normalize(value):
    identity, name = value.get('patient_id'), value.get('name')
    if not isinstance(identity, str) or not PATIENT_ID.fullmatch(identity.strip()):
        raise RegistryError(422, 'Patient identifier must contain 3-64 ASCII letters, digits, underscores or hyphens')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(
            unicodedata.category(char).startswith('C') for char in name):
        raise RegistryError(422, 'Patient name must contain 1-80 characters without control characters')
    sex, birth = value.get('sex', 'unknown'), value.get('birth_date')
    if sex not in ('female', 'male', 'unknown'):
        raise RegistryError(422, 'Patient sex must be female, male or unknown')
    if birth is not None:
        try:
            valid = isinstance(birth, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', birth) and dt.date.fromisoformat(birth) <= dt.date.today()
        except ValueError:
            valid = False
        if not valid:
            raise RegistryError(422, 'Birth date must be a valid ISO date no later than today')
    return {'patient_id': identity.strip(), 'name': name.strip(), 'sex': sex, 'birth_date': birth}


def _public(row):
    return {**{key: row[key] for key in ('patient_id', 'name', 'sex', 'birth_date', 'created_at')},
            'source': 'registered'}


def patients(con, archived):
    result = {}
    for patient in archived:
        identity, name = patient['patient_id'], patient['name']
        if identity in result and result[identity]['name'] != name:
            raise RegistryError(409, 'Patient identifier has conflicting names; identity review is required')
        result[identity] = {'patient_id': identity, 'name': name, 'sex': 'unknown', 'birth_date': None,
                            'source': 'archived', 'created_at': patient.get('created_at')}
    for row in con.execute('SELECT patient_id,name,sex,birth_date,created_at FROM patient_registry ORDER BY created_at,patient_id'):
        if row['patient_id'] in result and result[row['patient_id']]['name'] != row['name']:
            raise RegistryError(409, 'Patient identifier has conflicting names; identity review is required')
        result[row['patient_id']] = _public(row)
    return sorted(result.values(), key=lambda item: (item['created_at'] or '', item['patient_id']), reverse=True)


def lookup(con, archived, patient_id):
    patient = next((item for item in patients(con, archived) if item['patient_id'] == patient_id), None)
    if patient is None:
        raise RegistryError(404, 'Selected patient was not found in the business registry')
    return patient


def register(con, archived, value, actor):
    patient = normalize(value)
    existing = next((item for item in patients(con, archived) if item['patient_id'] == patient['patient_id']), None)
    if existing:
        if existing['name'] != patient['name']:
            raise RegistryError(409, 'Patient identifier has conflicting names; identity review is required')
        if existing['source'] == 'registered':
            if any(existing[key] != patient[key] for key in patient):
                raise RegistryError(409, 'Patient registration already exists with different details')
            return {'patient': existing, 'created': False}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    con.execute('INSERT INTO patient_registry VALUES(?,?,?,?,?,?)',
                (patient['patient_id'], patient['name'], patient['sex'], patient['birth_date'], now, actor))
    return {'patient': {**patient, 'source': 'registered', 'created_at': now}, 'created': True}


def associate(con, job_id, patient, actor):
    """Insert once inside the job transaction; there is deliberately no rebind operation."""
    context = {'patient_id': patient['patient_id'], 'name': patient['name'], 'source': 'operator_selected',
               'actor': actor, 'selected_at': dt.datetime.now(dt.timezone.utc).isoformat()}
    con.execute('INSERT INTO job_patient_association VALUES(?,?,?,?,?,?)',
                (job_id, context['patient_id'], context['name'], context['source'], context['actor'], context['selected_at']))
    return context


def context(con, job_id):
    row = con.execute('SELECT patient_id,name,source,actor,selected_at FROM job_patient_association WHERE job_id=?',
                      (job_id,)).fetchone()
    return dict(row) if row else None


def validate_candidate(candidate, selected):
    if selected is not None and (not isinstance(candidate, dict) or
            candidate.get('patient_id') != selected['patient_id'] or candidate.get('name') != selected['name']):
        raise RegistryError(409, 'Selected patient does not match the document identity')


def validate_registered_identity(con, candidate):
    """Historical unbound work cannot contradict an identity registered since upload."""
    if not isinstance(candidate, dict):
        return
    registered = con.execute('SELECT name FROM patient_registry WHERE patient_id=?',
                             (candidate.get('patient_id'),)).fetchone()
    if registered and candidate.get('name') != registered['name']:
        raise RegistryError(409, 'Patient identifier has conflicting names; identity review is required')


def duplicate(con, row, selected):
    """Never reuse a global source hash under a different or unknown patient identity."""
    if selected is None:
        return
    bound = context(con, row['id'])
    if bound is None:
        try:
            bound = json.loads(row['candidate']) if row['candidate'] else None
        except (TypeError, ValueError):
            bound = None
    if not bound or not bound.get('patient_id') or not bound.get('name'):
        raise RegistryError(409, 'Existing document has no confirmed patient binding; identity review is required')
    if bound['patient_id'] != selected['patient_id'] or bound['name'] != selected['name']:
        raise RegistryError(409, 'This document is already associated with a different patient')


def detail(con, patient, archived):
    projection = next((item for item in archived if item['patient_id'] == patient['patient_id']), None)
    visits = projection['visits'] if projection else []
    clinical_context = {key: [] for key in CONTEXT_CODES}
    for visit in visits:
        for fact in visit['facts']:
            code = fact.get('code')
            group = 'medications' if code == 'prescription' else code
            if group not in clinical_context:
                continue
            item = {'date': visit['date'], 'value': fact['value'], 'unit': fact.get('unit', ''),
                    'quote': fact.get('quote', ''), 'code': code,
                    'source_job': fact.get('source_job', visit.get('source_job')),
                    'current': fact.get('current', True),
                    'verification': 'legacy_archive' if visit.get('legacy') else 'reviewed_archive'}
            if fact.get('observation'):
                item['observation'] = fact['observation']
            clinical_context[group].append(item)
    for values in clinical_context.values():
        values.sort(key=lambda item: (item['date'], item.get('source_job') or ''))
    documents = []
    for row in con.execute('''SELECT jobs.id,jobs.filename,jobs.state,jobs.created,jobs.candidate,
            job_patient_association.patient_id,job_patient_association.name
            FROM jobs LEFT JOIN job_patient_association ON jobs.id=job_patient_association.job_id ORDER BY jobs.created DESC'''):
        if row['patient_id'] is not None:
            matches = row['patient_id'] == patient['patient_id'] and row['name'] == patient['name']
        else:
            try:
                candidate = json.loads(row['candidate']) if row['candidate'] else {}
            except (TypeError, ValueError):
                candidate = {}
            matches = candidate.get('patient_id') == patient['patient_id'] and candidate.get('name') == patient['name']
        if matches:
            documents.append({key: row[key] for key in ('id', 'filename', 'state', 'created')})
    return {**patient, 'visits': visits, 'clinical_context': clinical_context, 'documents': documents}
