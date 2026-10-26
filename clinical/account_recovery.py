"""Browser-bound recovery with explicit local operator approval, never HTTP approval."""
import argparse
import hashlib
import json
import pathlib
import secrets
import sqlite3
import sys
import time
import uuid

import accounts

PENDING_SECONDS = 15 * 60
APPROVED_SECONDS = 10 * 60
MAX_PENDING = 4096
MAX_REQUESTS = 8192
REQUEST_COLUMNS = 'id,username,state,expires,user_id,approved_expires'
ERROR = 'Password recovery is unavailable or expired'
LIMIT_ERROR = 'Too many recovery requests; try again later'


def _public(row, now):
    state = row['state']
    expires = row['expires']
    if state == 'approved':
        expires = min(expires, row['approved_expires'])
    if state == 'invalidated' or (state != 'consumed' and expires <= now):
        state = 'expired'
    return {'status': state, 'request_id': row['id'], 'username': row['username'],
            'expires_at': expires}


def _request_by_cookie(con, cookie):
    digest = accounts._token_digest(cookie)
    return con.execute('SELECT ' + REQUEST_COLUMNS + ' FROM recovery_requests WHERE digest=?', (digest,)).fetchone() if digest else None


def _rate_limit(con, username, client, now):
    con.execute('DELETE FROM recovery_attempts WHERE expires<=?', (now,))
    keys = [(hashlib.sha256(('user:' + username).encode()).hexdigest(), 3),
            (hashlib.sha256(('client:' + str(client)[:256]).encode()).hexdigest(), 15)]
    if con.execute('SELECT COUNT(*) FROM recovery_attempts').fetchone()[0] >= accounts.MAX_BUCKETS:
        raise accounts.AccountError(429, LIMIT_ERROR)
    # Preserve recovery history and stop bounded metadata growth without deleting it.
    if con.execute('SELECT COUNT(*) FROM recovery_requests').fetchone()[0] >= MAX_REQUESTS:
        raise accounts.AccountError(429, LIMIT_ERROR)
    if con.execute("SELECT COUNT(*) FROM recovery_requests WHERE state IN ('pending','approved') AND expires>?",
                   (now,)).fetchone()[0] >= MAX_PENDING:
        raise accounts.AccountError(429, LIMIT_ERROR)
    for key, limit in keys:
        row = con.execute('SELECT count FROM recovery_attempts WHERE key=?', (key,)).fetchone()
        if row and row['count'] >= limit:
            raise accounts.AccountError(429, LIMIT_ERROR)
    for key, _ in keys:
        con.execute('INSERT INTO recovery_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',
                    (key, now + PENDING_SECONDS))


def request_recovery(username, cookie, client):
    """Return the same public shape for active, missing and disabled usernames."""
    username = accounts._username(username)
    now = time.time()
    with accounts._db() as con:
        con.execute('BEGIN IMMEDIATE')
        previous = _request_by_cookie(con, cookie)
        if previous and previous['username'] == username and _public(previous, now)['status'] in ('pending', 'approved'):
            return _public(previous, now), cookie
        _rate_limit(con, username, client, now)
        # Bind the immutable identity now, so a later same-name account cannot inherit recovery.
        user = con.execute('SELECT id FROM users WHERE username=? AND active=1', (username,)).fetchone()
        token = secrets.token_urlsafe(32)
        request_id = uuid.uuid4().hex
        con.execute('INSERT INTO recovery_requests VALUES(?,?,?,?,?,?,?,?)',
                    (request_id, accounts._token_digest(token), username, now, now + PENDING_SECONDS,
                     'pending', user['id'] if user else None, None))
        row = con.execute('SELECT ' + REQUEST_COLUMNS + ' FROM recovery_requests WHERE id=?', (request_id,)).fetchone()
        return _public(row, now), token


def state(cookie):
    with accounts._db() as con:
        row = _request_by_cookie(con, cookie)
        return _public(row, time.time()) if row else {'status': 'none'}


def _eligible_user(con, row):
    if row is None or row['user_id'] is None:
        raise accounts.AccountError(409, ERROR)
    user = con.execute('SELECT id,username,active FROM users WHERE id=? AND username=? AND active=1',
                       (row['user_id'], row['username'])).fetchone()
    if user is None:
        raise accounts.AccountError(409, ERROR)
    return user


def _audit(con, user, event):
    con.execute('''CREATE TABLE IF NOT EXISTS password_recovery_audit (
        id TEXT PRIMARY KEY, at REAL NOT NULL, user_id TEXT NOT NULL,
        username TEXT NOT NULL, event TEXT NOT NULL)''')
    con.execute('INSERT INTO password_recovery_audit VALUES(?,?,?,?,?)',
                (uuid.uuid4().hex, time.time(), user['id'], user['username'], event))


def approve(database, request_id, username):
    """Approve an exact public request inside an existing local store, without credentials."""
    username = accounts._username(username)
    path = pathlib.Path(database).resolve()
    con = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT ' + REQUEST_COLUMNS + ' FROM recovery_requests WHERE id=? AND username=?',
                              (request_id, username)).fetchone()
            now = time.time()
            if row is None or _public(row, now)['status'] not in ('pending', 'approved'):
                raise accounts.AccountError(409, ERROR)
            user = _eligible_user(con, row)
            if row['state'] == 'approved':
                return _public(row, now)
            con.execute("UPDATE recovery_requests SET state='invalidated' WHERE user_id=? AND state='approved'",
                        (user['id'],))
            con.execute("UPDATE recovery_requests SET state='approved',approved_expires=? WHERE id=?",
                        (min(now + APPROVED_SECONDS, row['expires']), row['id']))
            _audit(con, user, 'browser_recovery_approved:' + row['id'])
            return _public(con.execute('SELECT ' + REQUEST_COLUMNS + ' FROM recovery_requests WHERE id=?', (row['id'],)).fetchone(), now)
    finally:
        con.close()


def complete(cookie, request_id, password, confirmation):
    """Consume one approved browser request and rotate its account atomically."""
    with accounts._db() as con:
        con.execute('BEGIN IMMEDIATE')
        row = _request_by_cookie(con, cookie)
        if row is None or row['id'] != request_id or _public(row, time.time())['status'] != 'approved':
            raise accounts.AccountError(409, ERROR)
        user = _eligible_user(con, row)
        encoded = accounts._password(password)
        if password != confirmation:
            raise accounts.AccountError(422, 'The two new passwords do not match')
        salt = secrets.token_bytes(32)
        replacement = accounts._hash(encoded, salt)
        # Hashing may cross expiry; recheck inside the same write transaction.
        if _public(row, time.time())['status'] != 'approved':
            raise accounts.AccountError(409, ERROR)
        con.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?', (salt, replacement, user['id']))
        con.execute('UPDATE sessions SET expires=0 WHERE user_id=?', (user['id'],))
        key = hashlib.sha256(('user:' + user['username']).encode()).hexdigest()
        con.execute('UPDATE attempts SET count=0,expires=0 WHERE key=?', (key,))
        accounts.invalidate_recovery_requests(con, user['username'])
        con.execute("UPDATE recovery_requests SET state='consumed' WHERE id=?", (row['id'],))
        _audit(con, user, 'password_reset_browser:' + row['id'])
        return {'reset': True, 'username': user['username']}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Approve a browser recovery request on this local machine')
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('approve')
    command.add_argument('--request-id', required=True)
    command.add_argument('--username', required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(approve('/data/accounts.sqlite', args.request_id, args.username)))
        return 0
    except accounts.AccountError as error:
        print(error.message, file=sys.stderr)
    except (sqlite3.Error, OSError):
        print('The existing recovery store is unavailable', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
