import sqlite3
from os import path, makedirs
from hashlib import sha256
import base64
from cryptography.fernet import Fernet
import os
from datetime import datetime

from flask import current_app, has_app_context

DB_DIR = path.join(path.dirname(__file__), '..', 'data')
DB_FILE = path.join(DB_DIR, 'targets.db')
KEY_FILE = path.join(DB_DIR, 'targets_key.key')


def _get_conn():
    makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _get_fernet():
    # Use a persistent key stored in data/targets_key.key so encrypted passwords
    # survive server restarts. If missing, create it.
    makedirs(DB_DIR, exist_ok=True)
    if not path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, 'wb') as f:
            f.write(key)
        return Fernet(key)
    with open(KEY_FILE, 'rb') as f:
        key = f.read().strip()
    return Fernet(key)


def _get_app_config():
    if has_app_context():
        return current_app.config

    from app import app
    return app.config


def _get_fernet_old(secret_key=None):
    # Backwards-compatible: derive key from SECRET_KEY used by older versions
    secret_key = secret_key or _get_app_config()['SECRET_KEY']
    key_bytes = sha256(secret_key.encode('utf-8')).digest()
    key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(key)


def init_db():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS targets (
        name TEXT PRIMARY KEY,
        host TEXT,
        port INTEGER,
        sid TEXT,
        service TEXT,
        encoding TEXT,
        user TEXT,
        password_encrypted BLOB,
        created_at TEXT,
        database_type TEXT NOT NULL DEFAULT 'oracle',
        database_name TEXT
    )
    ''')
    columns = {row['name'] for row in cur.execute('PRAGMA table_info(targets)')}
    if 'database_type' not in columns:
        cur.execute("ALTER TABLE targets ADD COLUMN database_type TEXT NOT NULL DEFAULT 'oracle'")
    if 'database_name' not in columns:
        cur.execute('ALTER TABLE targets ADD COLUMN database_name TEXT')
    conn.commit()
    conn.close()


def migrate_from_config(config=None):
    init_db()
    # If DB empty, populate from app.config['TARGETS']
    config = config or _get_app_config()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('SELECT count(1) as c FROM targets')
    if cur.fetchone()['c'] == 0:
        f = _get_fernet()
        for name, desc in config.get('TARGETS', {}).items():
            host = desc.get('host')
            port = desc.get('port')
            sid = desc.get('sid')
            service = desc.get('service')
            encoding = desc.get('encoding')
            user = desc.get('user')
            password = desc.get('password')
            enc = f.encrypt(password.encode('utf-8')) if password else None
            cur.execute('INSERT OR REPLACE INTO targets (name, host, port, sid, service, encoding, user, password_encrypted, created_at, database_type, database_name) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (name, host, port, sid, service, encoding, user, enc, datetime.utcnow().isoformat(),
                         desc.get('database_type', 'oracle'), desc.get('database_name')))
        conn.commit()
    conn.close()


def list_targets(secret_key=None):
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM targets ORDER BY name')
    rows = cur.fetchall()
    f = _get_fernet()
    result = []
    old_f = _get_fernet_old(secret_key)
    for r in rows:
        pwd = None
        enc_blob = r['password_encrypted']
        if enc_blob:
            try:
                pwd = f.decrypt(enc_blob).decode('utf-8')
            except Exception:
                # Attempt to decrypt with old key (in case key derivation changed)
                try:
                    pwd = old_f.decrypt(enc_blob).decode('utf-8')
                    # Re-encrypt with new key and update DB
                    new_enc = f.encrypt(pwd.encode('utf-8'))
                    cur.execute('UPDATE targets SET password_encrypted = ? WHERE name = ?', (new_enc, r['name']))
                    conn.commit()
                except Exception:
                    pwd = None
        result.append({
            'name': r['name'],
            'host': r['host'],
            'port': r['port'],
            'sid': r['sid'],
            'service': r['service'],
            'encoding': r['encoding'],
            'user': r['user'],
            'password': pwd,
            'database_type': r['database_type'],
            'database_name': r['database_name'],
            'created_at': r['created_at']
        })
    conn.close()
    return result


def group_targets_by_database(targets):
    """Group targets by database type, sorting target names within each group."""
    if isinstance(targets, dict):
        items = targets.items()
    else:
        items = ((target['name'], target) for target in targets)

    groups = {}
    for name, target in items:
        database_type = target.get('database_type') or 'oracle'
        label = {
            'oracle': 'Oracle',
            'postgresql': 'PostgreSQL',
        }.get(database_type, database_type.replace('_', ' ').title())
        groups.setdefault(database_type, {'label': label, 'targets': []})['targets'].append(
            (name, target)
        )

    database_order = {'oracle': 0, 'postgresql': 1}
    ordered_types = sorted(
        groups,
        key=lambda database_type: (
            database_order.get(database_type, 2),
            database_type.casefold(),
        ),
    )
    return [
        (
            groups[database_type]['label'],
            sorted(groups[database_type]['targets'], key=lambda item: item[0].casefold()),
        )
        for database_type in ordered_types
    ]


def add_target(name, host, port, sid, service, encoding, user, password, database_type='oracle',
               database_name=None):
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    f = _get_fernet()
    enc = f.encrypt(password.encode('utf-8')) if password else None
    cur.execute('INSERT OR REPLACE INTO targets (name, host, port, sid, service, encoding, user, password_encrypted, created_at, database_type, database_name) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (name, host, port, sid, service, encoding, user, enc, datetime.utcnow().isoformat(), database_type,
                 database_name))
    conn.commit()
    conn.close()


def delete_target(name):
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM targets WHERE name = ?', (name,))
    conn.commit()
    conn.close()


def get_targets_dict(secret_key=None):
    """Return a dict suitable for app.config['TARGETS'] with decrypted password."""
    rows = list_targets(secret_key)
    d = {}
    for r in rows:
        entry = {
            'host': r['host'],
            'port': r['port'],
            'sid': r['sid'],
            'service': r['service'],
            'encoding': r['encoding'],
            'user': r['user'],
            'password': r['password'],
            'database_type': r['database_type'],
            'database_name': r['database_name'],
        }
        d[r['name']] = entry
    return d
