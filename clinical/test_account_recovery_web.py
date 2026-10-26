"""Recovery checks use fresh synthetic accounts, local doubles and no real credentials."""
import concurrent.futures
import hashlib
import importlib
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import account_recovery as recovery
import accounts
import outbox
import recover_account


class RecoveryWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.temp.name) / 'accounts.sqlite'
        self.previous = accounts.DATABASE
        accounts.initialize(self.path)
        self.old = 'Synthetic-original-password'
        self.new = 'Synthetic-replacement-password'
        self.user, self.session = accounts.setup('synthetic-admin', self.old)
        self.staff = accounts.create_user('synthetic-staff', self.old, 'staff')
        _, self.staff_session = accounts.login('synthetic-staff', self.old, 'synthetic-client')

    def tearDown(self):
        accounts.DATABASE = self.previous
        self.temp.cleanup()

    def request(self, username='synthetic-admin', cookie='', client='synthetic-client'):
        return recovery.request_recovery(username, cookie, client)

    def approved(self, username='synthetic-admin'):
        public, cookie = self.request(username)
        recovery.approve(self.path, public['request_id'], username)
        return public, cookie

    def complete(self, public, cookie, **values):
        return recovery.complete(cookie, public['request_id'], values.get('password', self.new),
                                 values.get('confirmation', self.new))

    def error(self, code, function, *args):
        with self.assertRaises(accounts.AccountError) as error:
            function(*args)
        self.assertEqual(error.exception.status, code)
        return error.exception.message

    def test_request_is_neutral_for_missing_disabled_and_existing(self):
        with accounts._db() as con:
            con.execute('UPDATE users SET active=0 WHERE id=?', (self.staff['id'],))
        for name in ('synthetic-admin', 'synthetic-staff', 'synthetic-missing'):
            public, cookie = self.request(name)
            self.assertEqual(set(public), {'status', 'request_id', 'username', 'expires_at'})
            self.assertEqual(public['status'], 'pending')
            self.assertNotIn(cookie, json.dumps(public))
            self.assertEqual(recovery.state(cookie), public)
            if name != 'synthetic-admin':
                self.error(409, recovery.approve, self.path, public['request_id'], name)

    def test_cookie_digest_only_is_stored_and_request_id_is_not_authority(self):
        public, cookie = self.approved()
        with accounts._db() as con:
            row = dict(con.execute('SELECT * FROM recovery_requests').fetchone())
        self.assertEqual(row['digest'], hashlib.sha256(cookie.encode()).hexdigest())
        self.assertNotIn(cookie, repr(row))
        self.assertEqual(recovery.state(public['request_id']), {'status': 'none'})
        self.error(409, self.complete, public, public['request_id'])
        self.error(409, self.complete, public, '')
        self.assertEqual(accounts.session(self.session), self.user)

    def test_reusing_cookie_retains_request_and_approval_without_extending_expiry(self):
        with patch('account_recovery.time.time', return_value=1000):
            public, cookie = self.request()
        with patch('account_recovery.time.time', return_value=1100):
            approved = recovery.approve(self.path, public['request_id'], 'synthetic-admin')
        self.assertEqual(approved['expires_at'], 1700)
        with patch('account_recovery.time.time', return_value=1200):
            self.assertEqual(self.request(cookie=cookie), (approved, cookie))
            self.assertEqual(recovery.approve(self.path, public['request_id'], 'synthetic-admin'), approved)
        with accounts._db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM password_recovery_audit').fetchone()[0], 1)

    def test_approval_is_capped_by_original_expiry_and_expires(self):
        with patch('account_recovery.time.time', return_value=1000):
            public, cookie = self.request()
        with patch('account_recovery.time.time', return_value=1800):
            approved = recovery.approve(self.path, public['request_id'], 'synthetic-admin')
            self.assertEqual(approved['expires_at'], 1900)
        with patch('account_recovery.time.time', return_value=1900):
            self.assertEqual(recovery.state(cookie)['status'], 'expired')
            self.error(409, self.complete, public, cookie)
            self.error(409, recovery.approve, self.path, public['request_id'], 'synthetic-admin')

    def test_pending_and_unapproved_expiry_are_not_completion_authority(self):
        with patch('account_recovery.time.time', return_value=1000):
            public, cookie = self.request()
            self.error(409, self.complete, public, cookie)
        with patch('account_recovery.time.time', return_value=1900):
            self.assertEqual(recovery.state(cookie)['status'], 'expired')
            self.error(409, self.complete, public, cookie)

    def test_approval_requires_exact_name_and_supersedes_previous_approval(self):
        first, first_cookie = self.approved()
        second, second_cookie = self.request()
        self.error(409, recovery.approve, self.path, second['request_id'], 'synthetic-staff')
        recovery.approve(self.path, second['request_id'], 'synthetic-admin')
        self.assertEqual(recovery.state(first_cookie)['status'], 'expired')
        self.assertEqual(recovery.state(second_cookie)['status'], 'approved')
        self.error(409, self.complete, first, first_cookie)

    def test_missing_target_cannot_become_eligible_by_later_account_creation(self):
        public, cookie = self.request('synthetic-later')
        accounts.create_user('synthetic-later', self.old, 'staff')
        self.error(409, recovery.approve, self.path, public['request_id'], 'synthetic-later')
        self.error(409, self.complete, public, cookie)

    def test_target_disable_or_rename_after_approval_is_rejected(self):
        public, cookie = self.approved()
        with accounts._db() as con:
            con.execute('UPDATE users SET active=0 WHERE id=?', (self.user['id'],))
        self.error(409, self.complete, public, cookie)
        with accounts._db() as con:
            con.execute('UPDATE users SET active=1,username=? WHERE id=?', ('synthetic-renamed', self.user['id']))
        self.error(409, self.complete, public, cookie)

    def test_success_revokes_target_sessions_preserves_other_account_and_metadata(self):
        _, second = accounts.login('synthetic-admin', self.old, 'second-client')
        public, cookie = self.approved()
        other, other_cookie = self.request()
        with accounts._db() as con:
            before = tuple(con.execute('SELECT id,username,role,active,created FROM users WHERE id=?', (self.user['id'],)).fetchone())
        self.assertEqual(self.complete(public, cookie), {'reset': True, 'username': 'synthetic-admin'})
        self.assertEqual(recovery.state(cookie)['status'], 'consumed')
        self.assertEqual(recovery.state(other_cookie)['status'], 'expired')
        self.assertIsNone(accounts.session(self.session))
        self.assertIsNone(accounts.session(second))
        self.assertEqual(accounts.session(self.staff_session), self.staff)
        self.assertEqual(accounts.login('synthetic-admin', self.new, 'new-check')[0], self.user)
        self.error(401, accounts.login, 'synthetic-admin', self.old, 'old-check')
        with accounts._db() as con:
            self.assertEqual(tuple(con.execute('SELECT id,username,role,active,created FROM users WHERE id=?', (self.user['id'],)).fetchone()), before)
            audit = [dict(row) for row in con.execute('SELECT * FROM password_recovery_audit')]
        self.assertNotIn(self.new, repr(audit))
        self.assertNotIn(cookie, repr(audit))
        self.error(409, self.complete, public, cookie)

    def test_invalid_password_or_mismatch_does_not_consume_approval(self):
        public, cookie = self.approved()
        for password, confirmation in (('short', 'short'), (self.new, self.new + '-different'), ('\ud800' * 12, '\ud800' * 12)):
            self.error(422, recovery.complete, cookie, public['request_id'], password, confirmation)
            self.assertEqual(recovery.state(cookie)['status'], 'approved')
            self.assertEqual(accounts.session(self.session), self.user)

    def test_cross_tab_cookie_replacement_cannot_change_the_wrong_account(self):
        first, first_cookie = self.approved()
        second, second_cookie = self.approved('synthetic-staff')
        self.error(409, self.complete, first, second_cookie)
        self.error(409, self.complete, second, first_cookie)
        self.assertEqual(accounts.login('synthetic-admin', self.old, 'check-admin')[0], self.user)
        self.assertEqual(accounts.login('synthetic-staff', self.old, 'check-staff')[0], self.staff)
        self.assertEqual(recovery.state(first_cookie)['status'], 'approved')
        self.assertEqual(recovery.state(second_cookie)['status'], 'approved')

    def test_concurrent_completion_has_exactly_one_winner(self):
        public, cookie = self.approved()
        def attempt(index):
            try:
                self.complete(public, cookie)
                return 200
            except accounts.AccountError as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(attempt, range(2))), [200, 409])
        with accounts._db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM password_recovery_audit WHERE event LIKE 'password_reset_browser:%'").fetchone()[0], 1)

    def test_audit_failure_rolls_back_credentials_sessions_and_approval(self):
        public, cookie = self.approved()
        with accounts._db() as con:
            con.execute("CREATE TRIGGER synthetic_audit_failure BEFORE INSERT ON password_recovery_audit BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
        with self.assertRaises(sqlite3.Error):
            self.complete(public, cookie)
        self.assertEqual(recovery.state(cookie)['status'], 'approved')
        self.assertEqual(accounts.session(self.session), self.user)
        self.assertEqual(accounts.login('synthetic-admin', self.old, 'old-check')[0], self.user)

    def test_approval_audit_failure_rolls_back_supersession(self):
        first, first_cookie = self.approved()
        second, second_cookie = self.request()
        with accounts._db() as con:
            con.execute("CREATE TRIGGER synthetic_audit_failure BEFORE INSERT ON password_recovery_audit BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
        with self.assertRaises(sqlite3.Error):
            recovery.approve(self.path, second['request_id'], 'synthetic-admin')
        self.assertEqual(recovery.state(first_cookie)['status'], 'approved')
        self.assertEqual(recovery.state(second_cookie)['status'], 'pending')

    def test_ordinary_password_change_invalidates_pending_and_approved(self):
        approved, approved_cookie = self.approved()
        pending, pending_cookie = self.request()
        accounts.change_password(self.session, self.old, self.new)
        for cookie in (approved_cookie, pending_cookie):
            self.assertEqual(recovery.state(cookie)['status'], 'expired')
        self.error(409, self.complete, approved, approved_cookie)

    def test_legacy_local_recovery_invalidates_pending_and_approved(self):
        approved, approved_cookie = self.approved()
        pending, pending_cookie = self.request()
        recover_account.reset_password(self.path, 'synthetic-admin', self.new, self.new)
        for cookie in (approved_cookie, pending_cookie):
            self.assertEqual(recovery.state(cookie)['status'], 'expired')
        self.error(409, self.complete, approved, approved_cookie)

    def test_recovery_limits_are_separate_and_expire(self):
        with patch('account_recovery.time.time', return_value=1000):
            first, cookie = self.request()
            self.request()
            self.request()
            self.error(429, self.request)
            self.assertEqual(self.request(cookie=cookie)[0], first)
            with accounts._db() as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM recovery_requests').fetchone()[0], 3)
                self.assertEqual(con.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 1)
        with patch('account_recovery.time.time', return_value=1900):
            self.assertEqual(self.request()[0]['status'], 'pending')

    def test_client_and_global_pending_limits(self):
        for index in range(15):
            self.request('synthetic-' + str(index))
        self.error(429, self.request, 'synthetic-another')
        with patch.object(recovery, 'MAX_PENDING', 15):
            self.error(429, self.request, 'synthetic-another', '', 'different-client')

    def test_completion_clears_only_target_username_login_throttle(self):
        for name in ('synthetic-admin', 'synthetic-staff'):
            for index in range(5):
                self.error(401, accounts.login, name, 'Incorrect-synthetic-password', 'attempt-' + str(index))
        public, cookie = self.approved()
        self.complete(public, cookie)
        self.assertEqual(accounts.login('synthetic-admin', self.new, 'check-admin')[0], self.user)
        self.error(429, accounts.login, 'synthetic-staff', self.old, 'check-staff')

    def test_local_approval_does_not_create_missing_store(self):
        missing = self.path.with_name('missing.sqlite')
        with self.assertRaises(sqlite3.OperationalError):
            recovery.approve(missing, 'public-id', 'synthetic-admin')
        self.assertFalse(missing.exists())

    def test_total_history_cap_preserves_existing_reuse_approval_and_completion(self):
        public, cookie = self.request()
        with patch.object(recovery, 'MAX_REQUESTS', 1):
            self.error(429, self.request, 'synthetic-staff')
            self.assertEqual(self.request(cookie=cookie), (public, cookie))
            recovery.approve(self.path, public['request_id'], 'synthetic-admin')
            self.assertTrue(self.complete(public, cookie)['reset'])

    def test_local_approval_selects_no_secret_columns(self):
        public, cookie = self.request()
        original = sqlite3.connect
        statements = []
        def tracked(*args, **kwargs):
            con = original(*args, **kwargs)
            con.set_trace_callback(statements.append)
            return con
        with patch.object(recovery.sqlite3, 'connect', side_effect=tracked):
            recovery.approve(self.path, public['request_id'], 'synthetic-admin')
        selects = [sql.lower() for sql in statements if sql.lstrip().lower().startswith('select')]
        self.assertTrue(selects)
        for sql in selects:
            for forbidden in ('*', 'digest', 'salt', 'password_hash', 'sessions'):
                self.assertNotIn(forbidden, sql)


class RecoveryHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.previous_accounts = accounts.DATABASE
        self.previous_outbox = outbox.DATABASE
        self.previous_server = sys.modules.get('server')
        self.previous_namespace = dict(self.previous_server.__dict__) if self.previous_server else None
        self.environment = patch.dict(os.environ, {'AGENT_DATA': str(self.root), 'AGENT_DEMO': '0',
                                                   'AGENT_DOCUMENT_MODE': 'local', 'AGENT_PORT': '13042'})
        self.environment.start()
        self.server = importlib.reload(self.previous_server) if self.previous_server else importlib.import_module('server')
        self.client = TestClient(self.server.app, base_url='http://localhost:13042',
                                 headers={'origin': 'http://localhost:13042'})
        self.old = 'Synthetic-http-original-password'
        self.new = 'Synthetic-http-replacement-password'
        accounts.setup('synthetic-admin', self.old)

    def tearDown(self):
        self.client.close()
        accounts.DATABASE = self.previous_accounts
        outbox.DATABASE = self.previous_outbox
        self.environment.stop()
        if self.previous_namespace is not None:
            self.server.__dict__.clear()
            self.server.__dict__.update(self.previous_namespace)
        else:
            sys.modules.pop('server', None)
        self.temp.cleanup()

    def request(self):
        return self.client.post('/api/auth/recovery/request', json={'username': 'synthetic-admin'})

    def body(self, request_id):
        return {'request_id': request_id, 'new_password': self.new, 'confirmation': self.new}

    def test_anonymous_cookie_and_json_are_secret_free_then_complete_requires_login(self):
        self.assertEqual(self.client.get('/api/auth/recovery/state').json(), {'status': 'none'})
        response = self.request()
        self.assertEqual(response.status_code, 200)
        cookie = response.headers['set-cookie'].lower()
        for marker in ('sjd_recovery_13042=', 'httponly', 'samesite=strict', 'path=/api/auth/recovery', 'max-age='):
            self.assertIn(marker, cookie)
        public = response.json()
        self.assertEqual(set(public), {'status', 'request_id', 'username', 'expires_at'})
        recovery.approve(self.root / 'accounts.sqlite', public['request_id'], public['username'])
        self.assertEqual(self.client.get('/api/auth/recovery/state').json()['status'], 'approved')
        response = self.client.post('/api/auth/recovery/complete', json=self.body(public['request_id']))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'reset': True, 'username': 'synthetic-admin'})
        self.assertIn('sjd_workbench_13042=', response.headers['set-cookie'])
        self.assertIn('max-age=0', response.headers['set-cookie'].lower())
        self.assertFalse(self.client.get('/api/auth/state').json()['authenticated'])
        self.assertEqual(self.client.post('/api/auth/login', json={'username': 'synthetic-admin', 'password': self.new}).status_code, 200)

    def test_origin_host_and_non_json_requests_rejected_without_echo(self):
        for route in ('request', 'complete'):
            url = '/api/auth/recovery/' + route
            body = {'username': 'synthetic-admin'} if route == 'request' else self.body('synthetic-id')
            for headers in ({'origin': 'https://outside.invalid'}, {'origin': ''}, {'host': 'outside.invalid'}):
                response = self.client.post(url, json=body, headers=headers)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertNotIn(self.new, response.text)
            response = self.client.post(url, content=json.dumps(body), headers={'content-type': 'text/plain'})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.headers['cache-control'], 'no-store')
        response = self.client.get('/api/auth/recovery/state', headers={'host': 'outside.invalid'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_wrong_cookie_id_and_unapproved_completion_are_generic(self):
        public = self.request().json()
        generic = {'detail': recovery.ERROR}
        response = self.client.post('/api/auth/recovery/complete', json=self.body(public['request_id']))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), generic)
        recovery.approve(self.root / 'accounts.sqlite', public['request_id'], public['username'])
        response = self.client.post('/api/auth/recovery/complete', json=self.body('wrong-public-id'))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), generic)
        self.client.cookies.clear()
        response = self.client.post('/api/auth/recovery/complete', json=self.body(public['request_id']))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), generic)

    def test_input_validation_and_mismatch_do_not_echo_or_consume(self):
        public = self.request().json()
        recovery.approve(self.root / 'accounts.sqlite', public['request_id'], public['username'])
        for payload in ({**self.body(public['request_id']), 'confirmation': 'Different-synthetic-password'},
                        {**self.body(public['request_id']), 'new_password': 'short'},
                        {**self.body(public['request_id']), 'unknown': self.new},
                        {**self.body(public['request_id']), 'new_password': 'x' * 129}):
            response = self.client.post('/api/auth/recovery/complete', json=payload)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(self.new, response.text)
            self.assertNotIn('x' * 129, response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(self.client.get('/api/auth/recovery/state').json()['status'], 'approved')

    def test_no_http_approval_route_and_demo_mode_is_disabled(self):
        self.assertEqual(self.client.post('/api/auth/recovery/approve', json={'request_id': 'public'}).status_code, 401)
        with patch.object(self.server, 'DEMO', True):
            self.assertEqual(self.request().status_code, 409)
            self.assertEqual(self.client.get('/api/auth/recovery/state').status_code, 409)
            self.assertEqual(self.client.post('/api/auth/recovery/complete', json=self.body('public')).status_code, 409)


if __name__ == '__main__':
    unittest.main()
