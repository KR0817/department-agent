"""Recovery tests use only fresh synthetic accounts and temporary stores."""
import contextlib
import io
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import accounts
import recover_account


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name) / 'accounts.sqlite'
        accounts.initialize(self.path)
        self.old = 'Synthetic-original-password'
        self.new = 'Synthetic-replacement-password'
        self.admin, self.session = accounts.setup('synthetic-admin', self.old)
        self.staff = accounts.create_user('synthetic-staff', self.old, 'staff')
        _, self.staff_session = accounts.login('synthetic-staff', self.old, 'test-client')

    def reset(self, **changes):
        values = dict(database=self.path, username='synthetic-admin',
                      password=self.new, confirmation=self.new)
        values.update(changes)
        return recover_account.reset_password(**values)

    def assert_original_usable(self):
        self.assertEqual(accounts.session(self.session), self.admin)
        self.assertEqual(accounts.login('synthetic-admin', self.old, 'old-check')[0], self.admin)

    def test_reset_revokes_all_target_sessions_preserves_identity_and_other_account(self):
        _, second = accounts.login('synthetic-admin', self.old, 'second-client')
        recovered = self.reset(username=' SYNTHETIC-ADMIN ')
        self.assertEqual(recovered, self.admin)
        self.assertIsNone(accounts.session(self.session))
        self.assertIsNone(accounts.session(second))
        self.assertEqual(accounts.session(self.staff_session), self.staff)
        self.assertEqual(accounts.login('synthetic-staff', self.old, 'staff-check')[0], self.staff)
        with self.assertRaises(accounts.AccountError):
            accounts.login('synthetic-admin', self.old, 'old-check')
        self.assertEqual(accounts.login('synthetic-admin', self.new, 'new-check')[0], self.admin)
        with accounts._db() as con:
            audit = dict(con.execute('SELECT * FROM password_recovery_audit').fetchone())
        self.assertEqual(audit['event'], 'password_reset_local_operator')
        self.assertEqual(audit['user_id'], self.admin['id'])
        self.assertNotIn(self.new, repr(audit))
        self.assertNotIn(self.new.encode(), self.path.read_bytes())

    def test_invalid_or_mismatched_password_preserves_original(self):
        for change in ({'password': 'short', 'confirmation': 'short'},
                       {'confirmation': 'Different-synthetic-password'},
                       {'password': '\ud800' * 12, 'confirmation': '\ud800' * 12}):
            with self.subTest(change=tuple(change)):
                with self.assertRaises(accounts.AccountError):
                    self.reset(**change)
                self.assert_original_usable()

    def test_missing_and_disabled_accounts_are_not_created_or_enabled(self):
        with self.assertRaises(accounts.AccountError):
            self.reset(username='missing-user')
        with accounts._db() as con:
            con.execute('UPDATE users SET active=0 WHERE id=?', (self.staff['id'],))
        with self.assertRaises(accounts.AccountError):
            self.reset(username='synthetic-staff')
        users = accounts.list_users()
        self.assertEqual(len(users), 2)
        self.assertFalse(next(user for user in users if user['id'] == self.staff['id'])['active'])
        self.assert_original_usable()

    def test_missing_database_is_not_created(self):
        missing = self.path.with_name('missing.sqlite')
        with self.assertRaises(sqlite3.OperationalError):
            self.reset(database=missing)
        self.assertFalse(missing.exists())
        self.assert_original_usable()

    def test_audit_failure_rolls_back_password_and_session_changes(self):
        with accounts._db() as con:
            con.execute('CREATE TABLE password_recovery_audit (unexpected TEXT)')
        with self.assertRaises(sqlite3.Error):
            self.reset()
        self.assert_original_usable()

    def test_reset_clears_only_the_target_username_throttle(self):
        for index in range(5):
            with self.assertRaises(accounts.AccountError):
                accounts.login('synthetic-admin', 'Incorrect-synthetic-password', 'attempt-' + str(index))
        self.reset()
        self.assertEqual(accounts.login('synthetic-admin', self.new, 'fresh-client')[0], self.admin)

    def test_reset_never_selects_stored_secret_columns(self):
        original = sqlite3.connect
        statements = []

        def tracked(*args, **kwargs):
            con = original(*args, **kwargs)
            con.set_trace_callback(statements.append)
            return con

        with patch.object(recover_account.sqlite3, 'connect', side_effect=tracked):
            self.reset()
        selects = [sql.lower() for sql in statements if sql.lstrip().lower().startswith('select')]
        self.assertEqual(len(selects), 1)
        for sql in selects:
            self.assertNotIn('*', sql)
            self.assertNotIn('salt', sql)
            self.assertNotIn('password_hash', sql)
            self.assertNotIn('sessions', sql)

    def test_noninteractive_cli_cannot_prompt_or_mutate(self):
        output = io.StringIO()
        with patch.object(recover_account.sys.stdin, 'isatty', return_value=False), \
                patch.object(recover_account.getpass, 'getpass') as prompt, \
                contextlib.redirect_stderr(output):
            self.assertEqual(recover_account.main(['--username', 'synthetic-admin']), 2)
        prompt.assert_not_called()
        self.assert_original_usable()

    def test_cancelled_confirmation_never_requests_a_password(self):
        with patch.object(recover_account.sys.stdin, 'isatty', return_value=True), \
                patch.object(recover_account.sys.stdout, 'isatty', return_value=True), \
                patch('builtins.input', return_value='wrong-account'), \
                patch.object(recover_account.getpass, 'getpass') as prompt:
            self.assertEqual(recover_account.main(['--username', 'synthetic-admin']), 2)
        prompt.assert_not_called()
        self.assert_original_usable()


if __name__ == '__main__':
    unittest.main()
