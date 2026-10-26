"""Local username accounts; credential and session material stays in its own store."""
import contextlib
import hashlib
import hmac
import pathlib
import re
import secrets
import sqlite3
import time
import uuid

TTL_SECONDS = 8 * 60 * 60
DATABASE = None
USERNAME = re.compile(r'[a-z0-9][a-z0-9._-]{2,63}\Z')
LOGIN_WINDOW = 60
MAX_BUCKETS = 4096
SCRYPT_N = 32768


class AccountError(Exception):
    """An intentionally public account error without underlying database details."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


@contextlib.contextmanager
def _db():
    if DATABASE is None:
        raise RuntimeError('Account store is not initialized')
    con = sqlite3.connect(DATABASE, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        with con:
            yield con
    finally:
        con.close()


def initialize(path):
    """Initialize a separate credential store; never import historical identities."""
    global DATABASE
    DATABASE = pathlib.Path(path)
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with _db() as con:
        con.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','staff')),
                active INTEGER NOT NULL CHECK(active IN (0,1)),
                salt BLOB NOT NULL, password_hash BLOB NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                expires REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS session_user ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS attempts (
                key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
        ''')
        con.executescript('''
            CREATE TABLE IF NOT EXISTS recovery_requests (
                id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, username TEXT NOT NULL,
                created REAL NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL,
                user_id TEXT, approved_expires REAL);
            CREATE INDEX IF NOT EXISTS recovery_username ON recovery_requests(username);
            CREATE TABLE IF NOT EXISTS recovery_attempts (
                key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
        ''')
    DATABASE.chmod(0o600)


def _username(value):
    if not isinstance(value, str):
        raise AccountError(422, 'Username must contain 3-64 letters, digits, dots, underscores or hyphens')
    normalized = value.strip().lower()
    if not USERNAME.fullmatch(normalized):
        raise AccountError(422, 'Username must contain 3-64 letters, digits, dots, underscores or hyphens')
    return normalized


def _password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 128:
        raise AccountError(422, 'Password must contain 12-128 characters')
    try:
        encoded = value.encode('utf-8')
    except UnicodeError:
        raise AccountError(422, 'Password must contain valid Unicode characters') from None
    if len(encoded) > 512:
        raise AccountError(422, 'Password must contain 12-128 characters')
    return encoded


def _hash(password, salt):
    return hashlib.scrypt(password, salt=salt, n=SCRYPT_N, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024)


def _public(row):
    return {key: bool(row[key]) if key == 'active' else row[key] for key in ('id', 'username', 'role', 'active')}


def _token_digest(token):
    if not isinstance(token, str) or not 20 <= len(token) <= 256:
        return None
    try:
        return hashlib.sha256(token.encode('ascii')).hexdigest()
    except UnicodeError:
        return None


def _new_session(con, user_id):
    now = time.time()
    con.execute('DELETE FROM sessions WHERE expires<=?', (now,))
    token = secrets.token_urlsafe(32)
    con.execute('INSERT INTO sessions VALUES(?,?,?)', (_token_digest(token), user_id, now + TTL_SECONDS))
    return token


def _insert_user(con, username, password, role):
    if role not in ('admin', 'staff'):
        raise AccountError(422, 'Role must be admin or staff')
    salt = secrets.token_bytes(32)
    identity = uuid.uuid4().hex
    try:
        con.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)',
                    (identity, username, role, 1, salt, _hash(password, salt), time.time()))
    except sqlite3.IntegrityError:
        raise AccountError(409, 'Username is already in use') from None
    return {'id': identity, 'username': username, 'role': role, 'active': True}


def setup_required():
    with _db() as con:
        return con.execute('SELECT 1 FROM users LIMIT 1').fetchone() is None


def setup(username, password):
    """Create exactly one initial administrator, even across concurrent workers."""
    username, password = _username(username), _password(password)
    with _db() as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            raise AccountError(409, 'Initial administrator is already configured')
        user = _insert_user(con, username, password, 'admin')
        return user, _new_session(con, user['id'])


def _rate_limit(username, client):
    now = time.time()
    keys = [(hashlib.sha256(('user:' + username).encode()).hexdigest(), 5),
            (hashlib.sha256(('client:' + str(client)[:256]).encode()).hexdigest(), 30)]
    with _db() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('DELETE FROM attempts WHERE expires<=?', (now,))
        if con.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] >= MAX_BUCKETS:
            raise AccountError(429, 'Too many login attempts; try again later')
        for key, limit in keys:
            row = con.execute('SELECT count FROM attempts WHERE key=?', (key,)).fetchone()
            if row and row['count'] >= limit:
                raise AccountError(429, 'Too many login attempts; try again later')
        for key, _ in keys:
            con.execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',
                        (key, now + LOGIN_WINDOW))
    return keys[0][0]


def login(username, password, client):
    """Use identical errors for missing, disabled and incorrect-password accounts."""
    try:
        username = _username(username)
    except AccountError:
        username = '__invalid__'
    key = _rate_limit(username, client)
    valid_input = True
    try:
        password = _password(password)
    except AccountError:
        valid_input = False
        password = b'invalid-password'
    with _db() as con:
        row = con.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        salt = row['salt'] if row else b'unknown-account-scrypt-salt-v1'
        expected = row['password_hash'] if row else bytes(64)
        valid = hmac.compare_digest(_hash(password, salt), expected)
        if not valid_input or not row or not row['active'] or not valid:
            raise AccountError(401, 'Invalid username or password')
        # Lock and re-read before issuing a session to reject concurrent password changes.
        con.execute('BEGIN IMMEDIATE')
        current = con.execute('SELECT * FROM users WHERE id=?', (row['id'],)).fetchone()
        if not current or not current['active'] or current['password_hash'] != expected:
            raise AccountError(401, 'Invalid username or password')
        con.execute('DELETE FROM attempts WHERE key=?', (key,))
        return _public(current), _new_session(con, row['id'])


def session(token):
    digest = _token_digest(token)
    if digest is None:
        return None
    with _db() as con:
        row = con.execute('SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id '
                          'WHERE sessions.digest=? AND sessions.expires>? AND users.active=1',
                          (digest, time.time())).fetchone()
        return _public(row) if row else None


def logout(token):
    digest = _token_digest(token)
    if digest is not None:
        with _db() as con:
            con.execute('DELETE FROM sessions WHERE digest=?', (digest,))


def list_users():
    with _db() as con:
        return [_public(row) for row in con.execute('SELECT id,username,role,active FROM users ORDER BY username')]


def create_user(username, password, role):
    """The HTTP caller must enforce administrator authorization before this call."""
    username, password = _username(username), _password(password)
    with _db() as con:
        con.execute('BEGIN IMMEDIATE')
        return _insert_user(con, username, password, role)


def change_password(token, current_password, new_password):
    new_password = _password(new_password)
    identity = session(token)
    if identity is None:
        raise AccountError(401, 'Sign in again')
    _rate_limit(identity['username'], 'password-change:' + identity['id'])
    valid_input = True
    try:
        current_password = _password(current_password)
    except AccountError:
        valid_input = False
        current_password = b'invalid-password'
    with _db() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id '
                          'WHERE sessions.digest=? AND sessions.expires>? AND users.active=1',
                          (_token_digest(token), time.time())).fetchone()
        if not row or not hmac.compare_digest(_hash(current_password, row['salt']), row['password_hash']) or not valid_input:
            raise AccountError(401, 'Invalid current password')
        salt = secrets.token_bytes(32)
        con.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?', (salt, _hash(new_password, salt), row['id']))
        invalidate_recovery_requests(con, row['username'])
        con.execute('DELETE FROM sessions WHERE user_id=?', (row['id'],))
        return _public(row), _new_session(con, row['id'])


def invalidate_recovery_requests(con, username):
    """Keep older approved browser requests from overriding a newer password."""
    try:
        con.execute("UPDATE recovery_requests SET state='invalidated' WHERE username=? AND state IN ('pending','approved')",
                    (username,))
    except sqlite3.OperationalError as error:
        # The standalone legacy helper can run before this release initializes its tables.
        if str(error) != 'no such table: recovery_requests':
            raise
