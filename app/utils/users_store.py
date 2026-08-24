import sqlite3
from os import path, makedirs
from datetime import datetime
import json
from flask import current_app, has_app_context
from werkzeug.security import generate_password_hash, check_password_hash

DB_DIR = path.join(path.dirname(__file__), '..', 'data')
DB_FILE = path.join(DB_DIR, 'users.db')


def _get_conn():
    makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT,
        targets_json TEXT,
        is_admin INTEGER DEFAULT 0,
        created_at TEXT
    )
    ''')
    conn.commit()
    conn.close()


def _get_app_config():
    if has_app_context():
        return current_app.config

    from app import app
    return app.config


def migrate_from_config(config=None):
    """Migrate users from app.config['USERS'] into the DB if DB empty."""
    init_db()
    config = config or _get_app_config()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('SELECT count(1) as c FROM users')
    if cur.fetchone()['c'] == 0:
        # app.config['USERS'] expected format: { 'user': ('password', ['TARGET1',...]) }
        configured_users = config.get('USERS', {})
        if not configured_users:
            configured_users = {
                'admin': ('admin', list(config.get('TARGETS', {}).keys()))
            }
            admin_group = {'admin'}
        else:
            admin_group = set(config.get('ADMIN_GROUP', []))

        for uname, val in configured_users.items():
            pwd = val[0]
            targets = val[1] if len(val) > 1 else []
            is_admin = 1 if uname in admin_group else 0
            pwd_hash = generate_password_hash(pwd)
            cur.execute('INSERT OR REPLACE INTO users (username, password_hash, targets_json, is_admin, created_at) VALUES (?,?,?,?,?)',
                        (uname, pwd_hash, json.dumps(targets), is_admin, datetime.utcnow().isoformat()))
        conn.commit()
    conn.close()


def list_users():
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM users ORDER BY username')
    rows = cur.fetchall()
    result = []
    for r in rows:
        targets = []
        if r['targets_json']:
            try:
                targets = json.loads(r['targets_json'])
            except Exception:
                targets = []
        result.append({
            'username': r['username'],
            'password_hash': r['password_hash'],
            'targets': targets,
            'is_admin': bool(r['is_admin']),
            'created_at': r['created_at']
        })
    conn.close()
    return result


def add_user(username, password, targets=None, is_admin=False):
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    pwd_hash = generate_password_hash(password)
    targets_json = json.dumps(targets or [])
    cur.execute('INSERT OR REPLACE INTO users (username, password_hash, targets_json, is_admin, created_at) VALUES (?,?,?,?,?)',
                (username, pwd_hash, targets_json, 1 if is_admin else 0, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def delete_user(username):
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM users WHERE username = ?', (username,))
    conn.commit()
    conn.close()


def set_user_admin(username, is_admin=True):
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('UPDATE users SET is_admin = ? WHERE username = ?', (1 if is_admin else 0, username))
    conn.commit()
    conn.close()


def set_user_targets(username, targets):
    """Set the list of allowed targets for a user."""
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('UPDATE users SET targets_json = ? WHERE username = ?', (json.dumps(targets or []), username))
    conn.commit()
    conn.close()


def set_user_password(username, new_password):
    """Set the password for a user."""
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    pwd_hash = generate_password_hash(new_password)
    cur.execute('UPDATE users SET password_hash = ? WHERE username = ?', (pwd_hash, username))
    conn.commit()
    conn.close()


def get_users_dict():
    """Return dict in the format used by app.config['USERS'] and list of admins."""
    users = list_users()
    d = {}
    admins = []
    for u in users:
        d[u['username']] = (u['password_hash'], u['targets'])
        if u['is_admin']:
            admins.append(u['username'])
    return d, admins


def verify_password(username, password):
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('SELECT password_hash FROM users WHERE username = ?', (username,))
    row = cur.fetchone()
    conn.close()
    if row:
        return check_password_hash(row['password_hash'], password)
    return False
