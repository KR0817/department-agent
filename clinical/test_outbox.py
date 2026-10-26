"""Queue behavior against fresh synthetic SQLite stores; no clinical services."""
import copy
import contextlib
from concurrent.futures import ThreadPoolExecutor
import json
import pathlib
import sqlite3
import tempfile
import unittest

import outbox


def candidate(patient='SIM-001', date='2026-10-23', name='Synthetic patient'):
    return {'patient_id': patient, 'name': name, 'visits': [
        {'date': date, 'event_id': 'am', 'facts': [{'code': 'pain', 'value': '3'}]},
        {'date': date, 'event_id': 'pm', 'facts': [{'code': 'igg', 'value': '18.2'}]}]}


def receipt(task='synthetic-task', start='2027-01-07', end='2027-02-04'):
    return {'task': task, 'window_start': start, 'window_end': end}


def payload(row, **changes):
    return {**{key: row[key] for key in ('revision', 'due_date', 'message', 'status')},
            'reason': 'Synthetic operator decision', **changes}


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.prior_database = outbox.DATABASE
        self.temp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.temp.name) / 'jobs.sqlite'
        outbox.initialize(self.path)

    def tearDown(self):
        outbox.DATABASE = self.prior_database
        self.temp.cleanup()

    def assert_error(self, status, function, *args):
        with self.assertRaises(outbox.OutboxError) as caught:
            function(*args)
        self.assertEqual(caught.exception.status, status)

    def audit(self):
        with contextlib.closing(sqlite3.connect(self.path)) as con:
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute('SELECT * FROM outbox_audit ORDER BY id')]

    def test_same_day_events_and_sources_share_obligation(self):
        first = outbox.candidate_ready('job-a', candidate())
        self.assertEqual(first, outbox.candidate_ready('job-a', candidate()))
        linked = outbox.candidate_ready('job-b', candidate())
        self.assertEqual(linked['id'], first['id'])
        self.assertEqual(linked['job_id'], 'job-a')
        self.assertEqual(linked['revision'], first['revision'] + 1)
        with contextlib.closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(json.loads(con.execute('SELECT job_ids FROM followup_outbox').fetchone()[0]), ['job-a', 'job-b'])
        outbox.candidate_ready('job-c', candidate(patient='SIM-002'))
        outbox.candidate_ready('job-d', candidate(date='2026-10-24'))
        self.assertEqual(len(outbox.rows()), 3)

    def test_latest_visit_and_pure_correction(self):
        source = candidate()
        source['visits'].append(candidate(date='2026-12-01')['visits'][0])
        item = outbox.candidate_ready('job-a', source, 30)
        self.assertEqual(item['due_date'], '2026-12-31')
        correction = copy.deepcopy(candidate(patient='SIM-CORRECTION'))
        for visit in correction['visits']:
            for fact in visit['facts']:
                fact['correction_of'] = 'old-observation'
        self.assertIsNone(outbox.candidate_ready('job-correction', correction))
        self.assertIsNone(outbox.publication_ready('job-correction', correction, receipt()))
        self.assertIsNone(outbox.publication_ready('job-empty', candidate(), {'task': None}))
        self.assertEqual(len(outbox.rows()), 1)

    def test_publication_is_idempotent_and_task_unique(self):
        draft = outbox.candidate_ready('job-a', candidate())
        item = outbox.publication_ready('job-a', candidate(), receipt())
        self.assertEqual(item['id'], draft['id'])
        self.assertEqual(item['status'], 'pending_send')
        self.assertEqual(item['due_date'], '2027-01-21')
        history = self.audit()
        self.assertEqual(item, outbox.publication_ready('job-a', candidate(), receipt()))
        self.assertEqual(history, self.audit())
        self.assert_error(409, outbox.publication_ready, 'job-other', candidate(patient='SIM-002'), receipt())
        self.assert_error(409, outbox.publication_ready, 'job-a', candidate(), receipt(task='different-task'))
        self.assertEqual(outbox.rows(), [item])

    def test_cancelled_draft_remains_cancelled_on_publication_and_retry(self):
        item = outbox.candidate_ready('job-a', candidate())
        cancelled = outbox.edit(item['id'], payload(item, status='cancelled'), 'reviewer-1')
        published = outbox.publication_ready('job-a', candidate(), receipt())
        self.assertEqual(published['status'], 'cancelled')
        self.assertEqual(published['task_id'], 'synthetic-task')
        self.assertEqual(published, outbox.publication_ready('job-a', candidate(), receipt()))
        self.assertEqual(outbox.candidate_ready('job-b', candidate())['status'], 'cancelled')
        self.assertLess(cancelled['revision'], published['revision'])

    def test_manual_edits_survive_retries_and_audit_is_append_only(self):
        item = outbox.publication_ready('job-a', candidate(), receipt())
        old_audit = self.audit()
        edited = outbox.edit(item['id'], payload(item, message='Updated synthetic follow-up', due_date='2027-01-25'), 'reviewer-2')
        self.assert_error(409, outbox.edit, item['id'], payload(item, status='cancelled'), 'reviewer-3')
        self.assertEqual(edited, outbox.publication_ready('job-a', candidate(), receipt()))
        current_audit = self.audit()
        self.assertEqual(current_audit[:-1], old_audit)
        self.assertEqual(current_audit[-1]['actor'], 'reviewer-2')
        self.assertEqual(json.loads(current_audit[-1]['detail'])['before']['message'], item['message'])

    def test_changed_review_interval_updates_default_but_preserves_user_due(self):
        first = outbox.candidate_ready('job-a', candidate())
        outbox.edit(first['id'], payload(first, due_date='2026-11-25'), 'reviewer-1')
        result = outbox.publication_ready('job-a', candidate(), receipt(start='2026-11-08', end='2026-12-06'))
        self.assertEqual(result['due_date'], '2026-11-25')
        self.assertEqual(result['window_start'], '2026-11-08')
        second = outbox.publication_ready('job-b', candidate(patient='SIM-002'),
                                          receipt(task='task-b', start='2026-11-08', end='2026-12-06'))
        self.assertEqual(second['due_date'], '2026-11-22')

    def test_pending_requires_reviewed_task_and_no_delivered_status(self):
        item = outbox.candidate_ready('job-a', candidate())
        for state in ('pending_send', 'delivered', 'sent', 'completed'):
            self.assert_error(422, outbox.edit, item['id'], payload(item, status=state), 'reviewer-1')
        self.assertEqual(outbox.rows(), [item])
        with contextlib.closing(sqlite3.connect(self.path)) as con:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("UPDATE followup_outbox SET status='delivered'")

    def test_completion_needs_reviewed_encounter_evidence_and_is_read_only(self):
        item = outbox.publication_ready('job-a', candidate(), receipt())
        for task in ({'id': 'synthetic-task', 'status': 'completed'},
                     {'id': 'synthetic-task', 'status': 'completed', 'completion_mode': 'reviewed-visit-only', 'evidence': []},
                     {'id': 'synthetic-task', 'status': 'delivered'}):
            self.assertEqual(outbox.sync_tasks([task]), [item])
        completed = outbox.sync_tasks([{'id': 'synthetic-task', 'status': 'completed',
            'completion_mode': 'reviewed-visit-only', 'evidence': ['Encounter/synthetic-visit']}])[0]
        self.assertEqual(completed['status'], 'completed')
        self.assert_error(409, outbox.edit, item['id'], payload(completed, status='draft'), 'reviewer-1')
        self.assertEqual(outbox.publication_ready('job-a', candidate(), receipt()), completed)
        self.assertEqual(outbox.sync_tasks([]), [completed])

    def test_clinical_cancellation_closes_without_delivery_or_reactivation(self):
        item = outbox.publication_ready('job-a', candidate(), receipt())
        cancelled = outbox.sync_tasks([{'id': item['task_id'], 'status': 'cancelled'}])[0]
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertEqual(outbox.sync_tasks([{'id': item['task_id'], 'status': 'requested'}]), [cancelled])
        self.assertEqual(outbox.publication_ready('job-a', candidate(), receipt()), cancelled)

    def test_input_validation_rolls_back_without_changing_history(self):
        item = outbox.candidate_ready('job-a', candidate())
        initial = self.audit()
        for changes in ({'due_date': '2026-02-30'}, {'due_date': '20260101'}, {'message': ''},
                        {'reason': ' '}, {'revision': True}, {'actor': 'forged'}):
            self.assert_error(422, outbox.edit, item['id'], payload(item, **changes), 'reviewer-1')
        self.assert_error(409, outbox.candidate_ready, 'job-b', candidate(name='Other synthetic person'))
        self.assert_error(422, outbox.candidate_ready, 'job-b', candidate(), 0)
        self.assert_error(422, outbox.publication_ready, 'job-b', candidate(), receipt(start='2027-03-01'))
        self.assertEqual(initial, self.audit())
        self.assertEqual(outbox.rows(), [item])

    def test_concurrent_sources_do_not_duplicate_obligations(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda index: outbox.candidate_ready('job-' + str(index), candidate()), range(8)))
        self.assertEqual(len({item['id'] for item in results}), 1)
        self.assertEqual(len(outbox.rows()), 1)
        with contextlib.closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(len(json.loads(con.execute('SELECT job_ids FROM followup_outbox').fetchone()[0])), 8)


if __name__ == '__main__':
    unittest.main()
