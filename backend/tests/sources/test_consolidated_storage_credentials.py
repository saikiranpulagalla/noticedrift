"""Isolated credential canaries and bounded shared-directory durability checks."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
from threading import Barrier

import pytest
from pydantic import ValidationError

from app.search.models import OrganicResult
from app.search.sanitize import sanitize_for_persistence
from app.sources.fetch import safe_target
from app.sources.models import SourceSnapshot, SourceFailure, SourceErrorCode
from app.sources.store import SnapshotStore

URL = 'https://issuer.example/notices/a'


def capture(body=b'Fictional notice bytes'):
    return SourceSnapshot(source_url=URL, final_url=URL, body=body,
        captured_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        content_type='text/plain', body_sha256=sha256(body).hexdigest())


@pytest.mark.parametrize('key', ['api_key', 'KEY', 'auth', 'credential', 'credentials',
    'session', 'session_id', 'AWSAccessKeyId', 'X-Amz-Credential', 'x-goog-signature',
    'client-secret', 'access_token', '%61uth'])
def test_credential_canaries_rejected_before_transport_and_persistence(tmp_path, key):
    url = URL + '?' + key + '=SYNTHETIC_CANARY'
    with pytest.raises(SourceFailure) as failure:
        safe_target(url)
    assert failure.value.code == SourceErrorCode.UNSAFE_URL
    with pytest.raises(ValidationError):
        OrganicResult(link=url)
    for field in ('source_url', 'final_url', 'redirect_chain'):
        values = capture().model_dump()
        values[field] = (url,) if field == 'redirect_chain' else url
        with pytest.raises(ValidationError):
            SourceSnapshot.model_validate(values)
    forged = capture().model_copy(update={'final_url': url})
    store = SnapshotStore(tmp_path)
    with pytest.raises(SourceFailure):
        store.put(forged)
    assert not list(tmp_path.glob('*.json'))
    assert not list(tmp_path.glob('.tmp-*'))
    assert 'SYNTHETIC_CANARY' not in json.dumps(sanitize_for_persistence({'link': url}))


@pytest.mark.parametrize('query', ['code=A2026', 'id=123', 'page=2', 'ref=A%2F2026'])
def test_legitimate_document_identifiers_remain_exact(tmp_path, query):
    url = URL + '?' + query
    assert safe_target(url)[-1].endswith(query)
    assert OrganicResult(link=url).link == url
    snapshot = capture().model_copy(update={'source_url': url, 'final_url': url})
    store = SnapshotStore(tmp_path)
    digest = store.put(snapshot)
    assert store.get(digest) == snapshot


@pytest.mark.parametrize('identical', [True, False])
def test_independent_instances_share_count_quota_and_preserve_evidence(tmp_path, identical):
    stores = [SnapshotStore(tmp_path, max_snapshots=1) for _ in range(2)]
    barrier = Barrier(2)

    def write(index):
        barrier.wait(timeout=3)
        try:
            return stores[index].put(capture(b'A' if identical or index == 0 else b'B'))
        except SourceFailure as exc:
            assert exc.code == SourceErrorCode.OVERSIZED
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, (0, 1)))
    assert len(list(tmp_path.glob('*.json'))) == 1
    assert len([value for value in results if value]) == (2 if identical else 1)
    assert not list(tmp_path.glob('.tmp-*'))
    for digest in results:
        if digest:
            assert stores[0].get(digest).body in (b'A', b'B')


def test_independent_instances_share_byte_quota(tmp_path):
    first = SnapshotStore(tmp_path).put(capture(b'A'))
    size = (tmp_path / (first + '.json')).stat().st_size
    store = SnapshotStore(tmp_path, max_snapshots=2, max_total_bytes=size)
    with pytest.raises(SourceFailure) as failure:
        store.put(capture(b'B'))
    assert failure.value.code == SourceErrorCode.OVERSIZED
    assert store.get(first) == capture(b'A')
    assert store.put(capture(b'A')) == first
    assert not list(tmp_path.glob('.tmp-*'))


def test_lock_contention_fails_closed_and_cleans_only_own_temporary(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.sources import store as module
    first, second = SnapshotStore(tmp_path), SnapshotStore(tmp_path)
    with first._directory_capacity_lock():
        clock = iter((0.0, 3.0))
        monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda _: None))
        with pytest.raises(SourceFailure) as failure:
            second.put(capture())
        assert failure.value.code == SourceErrorCode.STORAGE_ERROR
    assert not list(tmp_path.glob('*.json'))
    assert not list(tmp_path.glob('.tmp-*'))


def worker_script():
    return '''
import sys, os
from pathlib import Path
from datetime import datetime, timezone
from hashlib import sha256
from app.sources.store import SnapshotStore
from app.sources.models import SourceSnapshot, SourceFailure
root, value, action = sys.argv[1:]
store = SnapshotStore(Path(root), max_snapshots=1)
body = value.encode()
snapshot = SourceSnapshot(source_url="https://issuer.example/a", final_url="https://issuer.example/a",
    captured_at=datetime(2026,10,1,tzinfo=timezone.utc), content_type="text/plain",
    body=body, body_sha256=sha256(body).hexdigest())
if action == "crash":
    with store._directory_capacity_lock():
        os._exit(0)
if action == "prepublication-crash":
    store._publish_atomically = lambda *args: os._exit(0)
try:
    print(store.put(snapshot), flush=True)
except SourceFailure as exc:
    print(exc.code.value, flush=True)
'''


def start_worker(root, value, action='put'):
    # No inherited provider credentials or private operator configuration.
    env = {'SystemRoot': os.environ.get('SystemRoot', r'C:\Windows'),
           'PYTHONPATH': str(Path(__file__).resolve().parents[2])}
    return subprocess.Popen([sys.executable, '-c', worker_script(), str(root), value, action],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def collect_worker(process):
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()  # Only this test-owned child, never an existing process.
        process.communicate(timeout=3)
        raise
    assert process.returncode == 0, stderr
    return stdout.strip()


def test_two_processes_cannot_exceed_shared_directory_quota(tmp_path):
    processes = [start_worker(tmp_path, value) for value in ('A', 'B')]
    outputs = [collect_worker(process) for process in processes]
    assert outputs.count('OVERSIZED') == 1
    artifacts = list(tmp_path.glob('*.json'))
    assert len(artifacts) == 1
    assert SnapshotStore(tmp_path).get(artifacts[0].stem).body in (b'A', b'B')
    assert not list(tmp_path.glob('.tmp-*'))


def test_process_exit_releases_os_lock(tmp_path):
    assert collect_worker(start_worker(tmp_path, 'unused', 'crash')) == ''
    store = SnapshotStore(tmp_path, max_snapshots=1)
    assert store.get(store.put(capture())) == capture()


def test_prepublication_crash_does_not_replace_prior_evidence(tmp_path):
    original = SnapshotStore(tmp_path).put(capture())
    # Permit the new write to reach publication in the isolated child.
    script = worker_script().replace('max_snapshots=1', 'max_snapshots=2')
    env = {'SystemRoot': os.environ.get('SystemRoot', r'C:\Windows'),
           'PYTHONPATH': str(Path(__file__).resolve().parents[2])}
    child = subprocess.Popen([sys.executable, '-c', script, str(tmp_path), 'B', 'prepublication-crash'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    assert collect_worker(child) == ''
    assert len(list(tmp_path.glob('*.json'))) == 1
    assert SnapshotStore(tmp_path).get(original) == capture()
