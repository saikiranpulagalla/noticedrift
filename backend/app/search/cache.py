"""Bounded, tamper-evident on-disk cache and recorded replay fixtures.

The serialized response digest is distinct from SerpApi's raw provider-response digest.
Disk modification is detected, not prevented; this is not a cryptographic signature.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from .models import SearchResponse, SearchMode
from .sanitize import sanitize_for_persistence

_KEY = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")

def _path(root: Path, key: str) -> Path:
    if not _KEY.fullmatch(key):
        raise ValueError("INVALID_STORAGE_KEY")
    path = root / (key + ".json")
    if path.resolve().parent != root.resolve():
        raise ValueError("INVALID_STORAGE_PATH")
    return path

def _canonical_bytes(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def _pack(data: object) -> bytes:
    clean = sanitize_for_persistence(data)
    digest = hashlib.sha256(_canonical_bytes(clean)).hexdigest()
    return _canonical_bytes({"schema": 2, "sha256": digest, "content": clean})

def _unpack(raw: bytes) -> object:
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("schema") != 2 or not isinstance(data.get("content"), dict):
        raise ValueError("INVALID_EVIDENCE_ENVELOPE")
    if hashlib.sha256(_canonical_bytes(data["content"])).hexdigest() != data.get("sha256"):
        raise ValueError("EVIDENCE_TAMPERED")
    return data["content"]

def _atomic_write(path: Path, data: bytes):
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".tmp-", delete=False) as f:
            name = f.name
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)

def request_key(engine: str, query: str, localization: dict[str, str]) -> str:
    payload = {"schema": 2, "engine": engine, "query": query.strip(),
               "provider_parameters": dict(sorted(localization.items()))}
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()

class LiveSearchCache:
    def __init__(self, root: Path, ttl: timedelta = timedelta(minutes=20)):
        self.root = Path(root)
        self.ttl = ttl
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str, now: datetime | None = None) -> SearchResponse | None:
        path = _path(self.root, key)
        if not path.exists():
            return None
        now = now or datetime.now(timezone.utc)
        try:
            data = _unpack(path.read_bytes())
            response = SearchResponse.model_validate(data)
            age = now - response.captured_at
            if age < timedelta(0) or age > self.ttl:
                return None
            return response.model_copy(update={"mode": SearchMode.LIVE_CACHE})
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            return None  # damaged cache is miss, never a trusted response

    def put(self, key: str, response: SearchResponse) -> None:
        path = _path(self.root, key)
        _atomic_write(path, _pack(response))

class ReplayEvidenceStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> SearchResponse | None:
        path = _path(self.root, key)
        if not path.exists():
            return None
        data = _unpack(path.read_bytes())  # tampering must not become cache miss
        if data.get("kind") == "raw":
            raise ValueError("USE_GET_RAW_FOR_RAW_CAPTURE")
        response = SearchResponse.model_validate(data)
        return response.model_copy(update={"mode": SearchMode.REPLAY})

    def put_once(self, key: str, response: SearchResponse) -> None:
        self._exclusive_write(_path(self.root, key), _pack(response))

    def put_raw_once(self, key: str, payload: dict, *, captured_at: datetime) -> None:
        """Captures sanitized raw JSON so replay tests the production parser."""
        data = {"kind": "raw", "payload": payload, "captured_at": captured_at.isoformat()}
        self._exclusive_write(_path(self.root, key), _pack(data))

    def get_raw(self, key: str):
        path = _path(self.root, key)
        if not path.exists():
            return None
        data = _unpack(path.read_bytes())
        if data.get("kind") != "raw" or not isinstance(data.get("payload"), dict):
            raise ValueError("NOT_RAW_PROVIDER_EVIDENCE")
        return data

    @staticmethod
    def _exclusive_write(path: Path, data: bytes):
        # Atomic create against competing writers; no check-then-write race.
        with path.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
