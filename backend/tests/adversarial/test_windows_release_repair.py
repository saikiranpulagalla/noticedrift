"""Windows release regressions: offline isolation, atomic evidence, and metadata."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import socket
import tomllib

import pytest

from app.sources.models import SourceErrorCode, SourceFailure, SourceSnapshot
from app.sources.store import SnapshotStore
from app.version import VERSION


def snapshot() -> SourceSnapshot:
    body = b'<main>Reference: A/2026</main>'
    return SourceSnapshot(
        source_url='https://issuer.example/a', final_url='https://issuer.example/a',
        captured_at=datetime.now(timezone.utc), content_type='text/html', body=body,
        body_sha256=sha256(body).hexdigest(),
    )


@pytest.mark.asyncio
async def test_offline_guard_allows_only_asyncio_socketpair_plumbing():
    await asyncio.sleep(0)
    assert await asyncio.gather(asyncio.sleep(0, result='one'), asyncio.sleep(0, result='two')) == ['one', 'two']
    started = asyncio.Event()

    async def cancellable():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(cancellable())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_offline_guard_still_blocks_external_and_direct_loopback_connections():
    for address in [('8.8.8.8', 53), ('127.0.0.1', 9)]:
        probe = socket.socket()
        try:
            with pytest.raises(AssertionError, match='OFFLINE_TEST_ATTEMPTED_REAL_NETWORK'):
                probe.connect(address)
        finally:
            probe.close()
    with pytest.raises(AssertionError, match='OFFLINE_TEST_ATTEMPTED_REAL_NETWORK'):
        socket.create_connection(('127.0.0.1', 9), timeout=0.01)


def test_snapshot_store_preserves_replay_and_distinct_capture_events(tmp_path):
    store = SnapshotStore(tmp_path, max_snapshots=2)
    first = snapshot()
    first_id = store.put(first)
    assert store.put(first) == first_id
    assert store.get(first_id).body == first.body
    second = first.model_copy(update={'captured_at': datetime.now(timezone.utc).replace(microsecond=1)})
    assert store.put(second) != first_id
    with pytest.raises(SourceFailure, match='OVERSIZED'):
        store.put(first.model_copy(update={'captured_at': datetime.now(timezone.utc).replace(microsecond=2)}))
    assert store.get(first_id).body == first.body


def test_atomic_publish_retries_a_transient_windows_permission_error(monkeypatch, tmp_path):
    store = SnapshotStore(tmp_path)
    original = store._publish_atomically
    calls = 0

    def flaky_replace(tmp, path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError('simulated sharing violation')
        return original_replace(tmp, path)

    original_replace = __import__('os').replace
    monkeypatch.setattr('app.sources.store.os.replace', flaky_replace)
    snapshot_id = store.put(snapshot())
    assert calls == 2
    assert store.get(snapshot_id).body == snapshot().body


def test_atomic_publish_permanent_permission_error_is_typed_and_cleans_temp(monkeypatch, tmp_path):
    store = SnapshotStore(tmp_path)
    monkeypatch.setattr('app.sources.store.os.replace', lambda *_: (_ for _ in ()).throw(PermissionError('denied')))
    with pytest.raises(SourceFailure) as exc:
        store.put(snapshot())
    assert exc.value.code == SourceErrorCode.STORAGE_ERROR
    assert list(tmp_path.glob('.tmp-*')) == []
    assert list(tmp_path.glob('*.json')) == []


def test_runtime_version_matches_package_and_judge_page():
    root = Path(__file__).resolve().parents[3]
    package = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    from app.api.main import create_app
    from app.api.site import SITE
    assert package['project']['version'] == VERSION
    assert f'v{VERSION}' in SITE
    assert create_app().version == VERSION
