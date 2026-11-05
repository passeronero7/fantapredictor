"""Immutable, hashed research bundles and prospective shadow records."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise ValueError('Invalid artifact identifier')
    return value


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def publish_bundle(root, version, artifacts, metadata):
    """Publish an immutable trained bundle. Approval cannot be asserted by a writer."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / identifier(version)
    if target.exists():
        raise FileExistsError(target)
    required = {'training_cutoff', 'data_hash', 'code_sha', 'features', 'model_type'}
    if required - set(metadata) or not artifacts:
        raise ValueError('Incomplete bundle metadata or artifacts')
    if metadata.get('status', 'trained') != 'trained':
        raise ValueError('Publishing does not grant approval')
    stage = Path(tempfile.mkdtemp(dir=root, prefix='.bundle-'))
    try:
        hashes = {}
        for name, source in artifacts.items():
            identifier(name)
            if name == 'manifest.json':
                raise ValueError('Reserved filename')
            shutil.copyfile(source, stage / name)
            hashes[name] = digest(stage / name)
        manifest = dict(metadata, version=version, status='trained', artifacts=hashes)
        (stage / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, allow_nan=False), encoding='utf-8')
        # rename refuses replacing a nonempty immutable bundle on POSIX.
        stage.rename(target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target


def verify_bundle(root, version):
    directory = Path(root) / identifier(version)
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != version or not manifest.get('artifacts'):
        raise ValueError('Invalid bundle manifest')
    for name, expected in manifest['artifacts'].items():
        identifier(name)
        path = directory / name
        if path.is_symlink() or digest(path) != expected:
            raise ValueError(f'Artifact integrity failure: {name}')
    return manifest


def record_shadow(root, run_id, cutoff, predictions, metadata):
    """Freeze predictions before the deadline using exclusive file creation."""
    deadline = datetime.fromisoformat(cutoff)
    now = datetime.now(timezone.utc)
    if deadline.tzinfo is None or deadline <= now:
        raise ValueError('Shadow deadline must be timezone-aware and in the future')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    payload = dict(metadata=metadata, predictions=predictions, cutoff=cutoff,
                   recorded_at=now.isoformat(), run_id=identifier(run_id))
    raw = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    fd, filename = tempfile.mkstemp(dir=root, prefix='.shadow-')
    os.close(fd)
    stage = Path(filename)
    try:
        stage.write_bytes(raw)
        target = root / (run_id + '.json')
        os.link(stage, target)  # atomic, exclusive publication
    finally:
        stage.unlink(missing_ok=True)
    return target
