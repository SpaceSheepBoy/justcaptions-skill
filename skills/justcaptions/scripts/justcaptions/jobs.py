"""Durable local jobs. Keys and media contents are never stored in job records."""
import json
import os
import sqlite3
import time
from pathlib import Path
from .execution import atomic_json

ACTIVE = ('queued', 'running', 'cancel_requested')

def directory():
    root = Path(os.environ.get('JUSTCAPTIONS_STATE_DIR', str(Path.home() / '.local/share/justcaptions'))).expanduser()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root

def connection():
    path = directory() / 'jobs.sqlite3'
    db = sqlite3.connect(path, timeout=10)
    os.chmod(path, 0o600)
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, pid INTEGER, status TEXT, updated REAL, payload TEXT)')
    return db

def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

def recover(db):
    for identity, pid, state, payload in db.execute("SELECT id,pid,status,payload FROM jobs WHERE status IN ('queued','running','cancel_requested')").fetchall():
        if not alive(pid):
            row = json.loads(payload)
            row.update(status='interrupted', stage='interrupted')
            db.execute('UPDATE jobs SET status=?, payload=? WHERE id=?', ('interrupted', json.dumps(row), identity))

def list_all(limit=50):
    with connection() as db:
        recover(db)
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM jobs ORDER BY updated DESC LIMIT ?', (limit,))]

def get(identity):
    with connection() as db:
        recover(db)
        row = db.execute('SELECT payload FROM jobs WHERE id=?', (identity,)).fetchone()
        if not row:
            raise ValueError('Unknown job ID. Use list_jobs to find saved jobs.')
        return json.loads(row[0])

def claim(row, resume=False):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        recover(db)
        previous = db.execute('SELECT status FROM jobs WHERE id=?', (row['job_id'],)).fetchone()
        if resume and (not previous or previous[0] in ACTIVE):
            raise ValueError('This job is already active or no longer exists.')
        if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','cancel_requested')").fetchone()[0] >= 2:
            raise ValueError('Two jobs are already active. Wait for one to finish.')
        row.update(status='queued', stage='queued')
        db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?)', (row['job_id'], os.getpid(), 'queued', time.time(), json.dumps(row)))

def save(row):
    with connection() as db:
        state = db.execute('SELECT status FROM jobs WHERE id=?', (row['job_id'],)).fetchone()
        if state and state[0] == 'cancel_requested' and row['status'] in ACTIVE:
            row['status'] = 'cancel_requested'
        db.execute('UPDATE jobs SET status=?,updated=?,payload=? WHERE id=?', (row['status'],time.time(),json.dumps(row),row['job_id']))

def cancel(identity):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        recover(db)
        record = db.execute('SELECT payload FROM jobs WHERE id=?', (identity,)).fetchone()
        if not record:
            raise ValueError('Unknown job ID.')
        row = json.loads(record[0])
        if row['status'] in ACTIVE:
            row.update(status='cancel_requested', stage='cancel_requested')
            db.execute('UPDATE jobs SET status=?,payload=? WHERE id=?', ('cancel_requested',json.dumps(row),identity))
        return row

def cancelled(identity):
    with connection() as db:
        row = db.execute('SELECT status FROM jobs WHERE id=?', (identity,)).fetchone()
        return row and row[0] == 'cancel_requested'

def fingerprint(path):
    path = Path(path).resolve()
    stat = path.stat()
    return {'path': str(path), 'size': stat.st_size, 'modified_ns': stat.st_mtime_ns}

def public(row):
    return {key: value for key,value in row.items() if key not in ('params','sources','caption_source','destination')}
