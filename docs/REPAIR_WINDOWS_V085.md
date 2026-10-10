# v0.8.5 Windows release repair

## Scope

This repair addresses the Windows test-isolation, evidence-store publication,
and displayed-release-identity findings from the controlled audit. It makes no
provider requests and changes neither source authorization nor governance
resolution semantics.

## Repairs

1. The offline test guard still denies every `socket.create_connection` and
   direct `socket.connect` call, with the existing
   `OFFLINE_TEST_ATTEMPTED_REAL_NETWORK` diagnostic. Its only intended
   exception is CPython's own `socket.py:socketpair` loopback construction,
   needed by Windows asyncio. Arbitrary local TCP connections remain denied.
2. `SnapshotStore` retains same-directory write, flush, `fsync`, SHA-256
   envelope verification, and `os.replace` publication. A sharing-related
   `PermissionError` gets only three bounded retries; a persistent denial is
   surfaced as `STORAGE_ERROR`, and cleanup removes the unpublished temporary
   file. There is no copy or direct-write fallback.
3. Filesystem tests use a private checkout-local temporary directory because
   the Codex AppContainer redirect for the system temp directory rejects
   atomic rename. The directory is removed after every test; this is test
   environment selection, not an application fallback.
4. `backend/app/version.py` is the runtime source of truth for FastAPI,
   `/health`, and the judge-page masthead. A regression compares it to
   `pyproject.toml`.

## Validation status

Python 3.12 was used for compilation, collection, and synchronous storage /
metadata regressions. The sandbox cannot execute Windows asyncio at all: a
plain `asyncio.run(asyncio.sleep(0))` stalls during the Proactor loopback
socketpair, even with no project monkeypatch. Full async suite, exact coverage,
three stability runs, Python 3.11, Python 3.13, and hosted Windows CI are
therefore **NOT TESTED** here. Live SerpApi and official-source gates remain
**NOT VERIFIED**.
