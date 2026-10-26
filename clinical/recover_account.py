"""Operator-only password recovery; the human supplies the secret in a TTY."""
import argparse
import getpass
import hashlib
import pathlib
import secrets
import sqlite3
import sys
import time
import uuid
import warnings

import accounts


def reset_password(database, username, password, confirmation):
    """Atomically recover one active account without reading old credential values."""
    username = accounts._username(username)
    encoded = accounts._password(password)
    if password != confirmation:
        raise accounts.AccountError(422, 'The two new passwords do not match')
    salt = secrets.token_bytes(32)
    replacement = accounts._hash(encoded, salt)
    path = pathlib.Path(database).resolve()
    # mode=rw prevents a typo from creating a new, unrelated credential store.
    con = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            con.execute('BEGIN IMMEDIATE')
            user = con.execute('SELECT id,username,role,active FROM users WHERE username=?',
                               (username,)).fetchone()
            if user is None or not user['active']:
                raise accounts.AccountError(404, 'The named active account was not found')
            con.execute('''CREATE TABLE IF NOT EXISTS password_recovery_audit (
                id TEXT PRIMARY KEY, at REAL NOT NULL, user_id TEXT NOT NULL,
                username TEXT NOT NULL, event TEXT NOT NULL)''')
            con.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?',
                        (salt, replacement, user['id']))
            accounts.invalidate_recovery_requests(con, username)
            con.execute('UPDATE sessions SET expires=0 WHERE user_id=?', (user['id'],))
            key = hashlib.sha256(('user:' + username).encode()).hexdigest()
            con.execute('UPDATE attempts SET count=0,expires=0 WHERE key=?', (key,))
            con.execute('INSERT INTO password_recovery_audit VALUES(?,?,?,?,?)',
                        (uuid.uuid4().hex, time.time(), user['id'], username,
                         'password_reset_local_operator'))
            return dict(user)
    finally:
        con.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Recover one existing local workbench account')
    parser.add_argument('--username', required=True)
    args = parser.parse_args(argv)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('An interactive terminal is required; redirected passwords are not accepted.', file=sys.stderr)
        return 2
    try:
        username = accounts._username(args.username)
        print('Local account recovery: ' + username)
        print('This replaces only this account password and expires its previous sessions.')
        print('Patient records and other accounts are preserved. Press Ctrl+C to cancel.')
        if input('Type the account name to confirm: ').strip().lower() != username:
            print('Cancelled. No account was changed.')
            return 2
        print('Use 12-128 characters. Password input is hidden.')
        # Never let getpass fall back to echoing a password on an unsuitable console.
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('New password: ')
            confirmation = getpass.getpass('Repeat new password: ')
        reset_password('/data/accounts.sqlite', username, password, confirmation)
        print('Password reset complete. Sign in at http://localhost:13032/ with your new password.')
        return 0
    except accounts.AccountError as error:
        print('Recovery not completed: ' + error.message, file=sys.stderr)
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print('\nCancelled or secure terminal input unavailable. No account was changed.', file=sys.stderr)
    except (sqlite3.Error, OSError):
        print('Recovery not completed: the existing account store could not be updated.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
