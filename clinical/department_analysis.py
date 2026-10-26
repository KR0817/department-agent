"""Read-only departmental adapter for the existing MingYiRx implementation."""
import hashlib
import importlib
import json
from pathlib import Path

from department_sources import load_package


MAX_PAYLOAD_BYTES = 256 * 1024
MAX_TEXT_CHARS = 100000
MAX_RECORDS = 100
DATA_ORIGINS = ('synthetic', 'deidentified')


class AnalysisError(Exception):
    """Safe HTTP error: input contents and filesystem details are never echoed."""

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _payload(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise AnalysisError(422, 'Exact analysis request fields are required')
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
        raise AnalysisError(422, 'Analysis values must be finite valid JSON') from None
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise AnalysisError(413, 'Analysis request exceeds 256 KiB')
    if value['data_origin'] not in DATA_ORIGINS:
        raise AnalysisError(422, 'Declare synthetic or deidentified input')


def _provenance(origin, reviewed):
    return {
        'data_origin': origin,
        'review_confirmed': reviewed,
        'data_origin_is_operator_declaration': True,
        'deidentification_verified': False,
        'source_hashes_independently_verified': False,
        'clinical_approval': None,
        'persisted': False,
    }


class Analysis:
    """Bind one authoritative checkout; this adapter never saves submitted data."""

    def __init__(self, root):
        try:
            package = load_package('department_mingyirx', Path(root) / 'src' / 'mingyirx')
            self._intake = importlib.import_module(package.__name__ + '.case_import')
            self._inheritance = importlib.import_module(package.__name__ + '.inheritance')
        except (OSError, ImportError, ValueError, AttributeError):
            raise AnalysisError(503, 'MingYiRx source package is unavailable') from None
        self.version = getattr(package, '__version__', 'unknown')

    def recognize(self, payload):
        """Reuse the original parser and retain source line evidence for review."""
        _payload(payload, ('text', 'data_origin'))
        text = payload['text']
        if not isinstance(text, str) or not text.strip():
            raise AnalysisError(422, 'Analysis text is required')
        if len(text) > MAX_TEXT_CHARS:
            raise AnalysisError(413, 'Analysis text exceeds 100000 characters')
        source_sha256 = hashlib.sha256(text.encode('utf-8')).hexdigest()
        content = text.lstrip('\ufeff \t\r\n')
        first_line = content.splitlines()[0]
        format_name = ('json' if content.startswith('[') else
                       'csv' if ',' in first_line and ':' not in first_line and '\uff1a' not in first_line else
                       'txt')
        try:
            result = self._intake.recognize_text(text, source_sha256, format_name)
        except self._intake.CaseImportError:
            raise AnalysisError(422, 'Analysis text could not be interpreted') from None
        if len(result['records']) > MAX_RECORDS:
            raise AnalysisError(413, 'At most 100 analysis records are allowed')
        return {**result, **_provenance(payload['data_origin'], False),
                'source_sha256': source_sha256, 'format': format_name,
                'software_version': self.version}

    def preview(self, payload):
        """Analyze explicitly reviewed candidates without granting clinical approval."""
        _payload(payload, ('records', 'data_origin', 'review_confirmed'))
        if payload['review_confirmed'] is not True:
            raise AnalysisError(422, 'Confirm candidate review before analysis')
        records = payload['records']
        if not isinstance(records, list) or not records:
            raise AnalysisError(422, 'A nonempty analysis record array is required')
        if len(records) > MAX_RECORDS:
            raise AnalysisError(413, 'At most 100 analysis records are allowed')
        synthetic = payload['data_origin'] == 'synthetic'
        try:
            result = self._intake.prepare_import(records, synthetic=synthetic)
            bundle = result['bundle']
            view = self._inheritance.build_view(bundle) if bundle else None
        except self._inheritance.InheritanceError:
            raise AnalysisError(422, 'Analysis candidates could not be validated') from None
        # The importer sets authorization flags for its caller-owned commit path.
        # A read-only real-data preview must never expose that executable bundle.
        result = {**result, 'bundle': bundle if synthetic else None,
                  'vocabulary': bundle['vocabulary'] if bundle else {},
                  'cases': bundle['cases'] if bundle else [], 'view': view,
                  **_provenance(payload['data_origin'], True),
                  'software_version': self.version}
        return result

    def example(self):
        """Return invented visits that exercise additions, removals and unknown dose basis."""
        text = (
            'subject_code: SYN-DEPARTMENT-001\n'
            'episode_code: SYN-EPISODE-001\n'
            'physician_code: SYN-PHYSICIAN-001\n'
            'visit_code: SYN-V1\n'
            'date: 2026-01-01\n'
            'sequence: 1\n'
            'condition: SYNTHETIC ONLY\n'
            'symptoms: simulated dryness; simulated fatigue\n'
            'tongue: simulated observation A\n'
            'pulse: not recorded\n'
            'syndrome: not recorded\n'
            'principle: not recorded\n'
            'prescription: HerbA 10g; HerbB 6g\n\n'
            'visit_code: SYN-V2\n'
            'date: 2026-01-15\n'
            'sequence: 2\n'
            'condition: SYNTHETIC ONLY\n'
            'symptoms: simulated dryness\n'
            'tongue: simulated observation B\n'
            'pulse: not recorded\n'
            'syndrome: not recorded\n'
            'principle: not recorded\n'
            'prescription: HerbA 12g; HerbC 8g\n\n'
            'visit_code: SYN-V3\n'
            'date: 2026-01-29\n'
            'sequence: 3\n'
            'condition: SYNTHETIC ONLY\n'
            'symptoms: not recorded\n'
            'tongue: not recorded\n'
            'pulse: not recorded\n'
            'syndrome: not recorded\n'
            'principle: not recorded\n'
            'prescription: HerbA 12g; HerbC 8g; HerbD 5g\n'
        )
        return {**self.recognize({'text': text, 'data_origin': 'synthetic'}),
                'text': text, 'example_version': 'department-analysis-synthetic-v1'}
