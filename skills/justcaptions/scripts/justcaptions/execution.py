"""Cooperative cancellation and private, atomic checkpoints for local jobs."""
import contextvars
import json
import os
import tempfile
from pathlib import Path

context = contextvars.ContextVar('justcaptions_execution', default=None)

class JobCancelled(RuntimeError):
    pass

def check():
    current = context.get()
    if current and current['cancelled']():
        raise JobCancelled('Job cancelled. Completed files and API checkpoints are retained.')

def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def digest(path):
    import hashlib
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            value.update(chunk)
    return value.hexdigest()
