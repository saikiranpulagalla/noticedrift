"""Content-addressed local snapshots with digest verification on every load.

Not an authenticated/cryptographically signed evidence store: local admins can
replace both content and metadata. Protect the directory with OS permissions.
"""
from __future__ import annotations
import json
import base64
from hashlib import sha256
import os
import re
import time
from threading import RLock
from pathlib import Path
from uuid import uuid4
from .models import SourceSnapshot, SourceFailure, SourceErrorCode

class SnapshotStore:
    def __init__(self, root: Path, *, max_snapshots: int = 1024,
                 max_total_bytes: int = 200_000_000):
        if not (1 <= max_snapshots <= 100_000) or not (1 <= max_total_bytes <= 10**10):
            raise ValueError('INVALID_EVIDENCE_STORAGE_BUDGET')
        self.root = Path(root)
        self.max_snapshots = max_snapshots
        self.max_total_bytes = max_total_bytes
        self._capacity_lock = RLock()   # Protects in-process concurrent puts.
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, digest: str) -> Path:
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise SourceFailure(SourceErrorCode.SOURCE_INTEGRITY_ERROR)
        return self.root / (digest + '.json')

    @staticmethod
    def _publish_atomically(tmp: Path, path: Path) -> None:
        """Atomically publish a completed same-directory envelope.

        Windows file sharing scanners can transiently deny a rename.  Retry a
        bounded number of times, but never replace this with a copy/direct
        write.  A persistent failure is a typed, fail-closed storage error.
        """
        last_error = None
        for delay in (0.0, 0.02, 0.05):
            if delay:
                time.sleep(delay)
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                last_error = exc
        raise SourceFailure(SourceErrorCode.STORAGE_ERROR) from last_error

    def put(self, snapshot: SourceSnapshot) -> str:
        # Base64 is deliberate: JSON envelope permits exact bytes, no lossy recoding.
        record = snapshot.model_dump(exclude={'body'}, mode='json')
        record['body_base64'] = base64.b64encode(snapshot.body).decode('ascii')
        payload = json.dumps(record, sort_keys=True, separators=(',', ':')).encode('utf-8')
        digest = sha256(payload).hexdigest()  # Cover URL/time/metadata AND body, not just body.
        path = self._path(digest)
        tmp = self.root / ('.tmp-' + uuid4().hex)
        try:
            with open(tmp, 'xb') as stream:
                if hasattr(os, 'fchmod'):
                    os.fchmod(stream.fileno(), 0o600)
                # On Windows <3.13 the file inherits its parent directory's
                # DACL. This standard-library fallback does not claim to set
                # an NTFS owner-only ACL; configure the directory privately.
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            # Retain every distinct capture event for forensic replay, but never
            # let the local snapshot archive grow without a hard bound. Refuse
            # new captures on exhaustion: no evidence is silently evicted.
            with self._capacity_lock:
                if path.exists():
                    existing = self.get(digest)
                    if existing.body != snapshot.body:
                        raise SourceFailure(SourceErrorCode.SOURCE_INTEGRITY_ERROR)
                else:
                    artifacts = tuple(self.root.glob('*.json'))
                    if len(artifacts) >= self.max_snapshots or (sum(p.stat().st_size for p in artifacts) + len(payload)) > self.max_total_bytes:
                        raise SourceFailure(SourceErrorCode.OVERSIZED)
                    self._publish_atomically(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return digest

    def get(self, digest: str) -> SourceSnapshot:
        path = self._path(digest)
        try:
            if path.stat().st_size > 13_000_000:
                raise ValueError()
            with path.open('rb') as stream:
                data = stream.read(13_000_001)
            if len(data) > 13_000_000:
                raise ValueError()
            record = json.loads(data)
            record['body'] = base64.b64decode(record.pop('body_base64'), validate=True)
            if sha256(data).hexdigest() != digest:
                raise ValueError()
            snapshot = SourceSnapshot.model_validate(record)
            return snapshot
        except (OSError, ValueError, TypeError, KeyError, __import__("binascii").Error):
            raise SourceFailure(SourceErrorCode.SOURCE_INTEGRITY_ERROR) from None
