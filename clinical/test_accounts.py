"""Account boundaries in new synthetic stores; no existing credentials are read."""
import concurrent.futures
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import accounts


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name) / 'accounts.sqlite'
        accounts.initialize(self.path)
        self.password = 'Synthetic-test-password-1'

    def assert_error(self, status, call, *args):
        with self.assertRaises(accounts.AccountError) as result:
            call(*args)
        self.assertEqual(result.exception.status, status)
        return result.exception.message

    def test_setup_is_atomic_and_normalizes_username(self):
        self.assertTrue(accounts.setup_required())

        def attempt(name):
            try:
                return accounts.setup(name, self.password)
            except accounts.AccountError as error:
                return error.status

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, [' ADMIN ', 'another-admin']))
        winners = [result for result in results if isinstance(result, tuple)]
        self.assertEqual(len(winners), 1)
        self.assertEqual(results.count(409), 1)
        self.assertEqual(winners[0][0]['role'], 'admin')
        self.assertFalse(accounts.setup_required())
        self.assertEqual(len(accounts.list_users()), 1)
        self.assertEqual(accounts.session(winners[0][1]), winners[0][0])

    def test_login_generic_errors_and_no_secrets_in_public_records(self):
        user, _ = accounts.setup('admin', self.password)
        missing = self.assert_error(401, accounts.login, 'nobody', self.password, 'synthetic-client')
        wrong = self.assert_error(401, accounts.login, 'admin', 'Incorrect-test-password', 'synthetic-client')
        self.assertEqual(missing, wrong)
        signed_in, token = accounts.login('ADMIN', self.password, 'synthetic-client')
        self.assertEqual(signed_in, user)
        self.assertEqual(accounts.session(token), user)
        self.assertEqual(set(signed_in), {'id', 'username', 'role', 'active'})
        self.assertEqual(accounts.list_users(), [user])
        with accounts._db() as con:
            salt, digest = con.execute('SELECT salt,password_hash FROM users').fetchone()
            tokens = [row[0] for row in con.execute('SELECT digest FROM sessions')]
        self.assertEqual(len(salt), 32)
        self.assertEqual(len(digest), 64)
        self.assertNotIn(token, tokens)
        self.assertNotIn(self.password.encode(), self.path.read_bytes())

    def test_validation_uniqueness_and_salted_hashes(self):
        accounts.setup('admin', self.password)
        self.assert_error(422, accounts.create_user, 'person@example.invalid', self.password, 'staff')
        self.assert_error(422, accounts.create_user, 'staff', 'short', 'staff')
        self.assert_error(422, accounts.create_user, 'staff', self.password, 'owner')
        self.assert_error(409, accounts.create_user, 'ADMIN', self.password, 'staff')
        accounts.create_user('staff', self.password, 'staff')
        with accounts._db() as con:
            values = list(con.execute('SELECT salt,password_hash FROM users'))
        self.assertNotEqual(values[0], values[1])

    def test_sessions_expire_logout_and_recheck_roles(self):
        with patch('accounts.time.time', return_value=1000):
            user, token = accounts.setup('admin', self.password)
            self.assertEqual(accounts.session(token), user)
        with patch('accounts.time.time', return_value=1000 + accounts.TTL_SECONDS):
            self.assertIsNone(accounts.session(token))
        with patch('accounts.time.time', return_value=1001):
            with accounts._db() as con:
                con.execute("UPDATE users SET role='staff'")
            self.assertEqual(accounts.session(token)['role'], 'staff')
            with accounts._db() as con:
                con.execute('UPDATE users SET active=0')
            self.assertIsNone(accounts.session(token))
            with accounts._db() as con:
                con.execute('UPDATE users SET active=1')
            accounts.logout(token)
            self.assertIsNone(accounts.session(token))
        self.assertIsNone(accounts.session(None))

    def test_password_rotation_revokes_all_sessions_and_persists(self):
        _, first = accounts.setup('admin', self.password)
        _, second = accounts.login('admin', self.password, 'synthetic-client')
        replacement = 'New-synthetic-test-password'
        user, token = accounts.change_password(first, self.password, replacement)
        self.assertIsNone(accounts.session(first))
        self.assertIsNone(accounts.session(second))
        self.assertEqual(accounts.session(token), user)
        accounts.initialize(self.path)
        self.assertEqual(accounts.session(token), user)
        self.assert_error(401, accounts.login, 'admin', self.password, 'synthetic-client')
        self.assertEqual(accounts.login('admin', replacement, 'synthetic-client')[0], user)

    def test_failed_password_change_preserves_session_and_hash(self):
        user, token = accounts.setup('admin', self.password)
        self.assert_error(401, accounts.change_password, token, 'Incorrect-password', 'New-synthetic-password')
        self.assertEqual(accounts.session(token), user)
        self.assertEqual(accounts.login('admin', self.password, 'synthetic-client')[0], user)

    def test_malformed_password_never_matches_dummy_hash_input(self):
        _, token = accounts.setup('admin', 'invalid-password')
        self.assert_error(401, accounts.login, 'admin', '', 'synthetic-client')
        self.assert_error(401, accounts.change_password, token, None, 'New-synthetic-password')
        self.assertIsNone(accounts.session('\ud800' * 32))
        self.assert_error(422, accounts.create_user, 'staff', '\ud800' * 12, 'staff')

    def test_login_throttle_persists_and_expires(self):
        accounts.setup('admin', self.password)
        with patch('accounts.time.time', return_value=2000):
            for _ in range(5):
                self.assert_error(401, accounts.login, 'admin', 'Incorrect-password', 'synthetic-client')
            accounts.initialize(self.path)
            self.assert_error(429, accounts.login, 'admin', self.password, 'synthetic-client')
        with patch('accounts.time.time', return_value=2000 + accounts.LOGIN_WINDOW):
            self.assertEqual(accounts.login('admin', self.password, 'synthetic-client')[0]['role'], 'admin')


if __name__ == '__main__':
    unittest.main()
