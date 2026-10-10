from datetime import datetime, timezone
import inspect
from pathlib import Path
import shutil
import tempfile
import pytest
from app.domain import *

UTC = timezone.utc


@pytest.fixture
def tmp_path():
    """Use a private checkout-local directory for filesystem integration tests.

    The Codex AppContainer's redirected system Temp directory denies atomic
    rename despite normal NTFS directories supporting it.  A same-volume,
    normal local directory exercises the supported evidence-store contract and
    is always removed after each test.
    """
    root = Path.cwd()
    created = Path(tempfile.mkdtemp(prefix='.noticedrift-test-', dir=root))
    try:
        yield created
    finally:
        shutil.rmtree(created, ignore_errors=True)

def dt(day: int):
    return datetime(2026, 10, day, 12, 0, tzinfo=UTC)

@pytest.fixture
def family():
    return NoticeFamily(
        family_id="fam-1", issuer_id="issuer-1", canonical_title="Research Notice",
        reference_aliases=frozenset({"ADV/01/2026"}), notice_year=2026,
        document_ids=frozenset({"orig", "ext", "withdraw", "cancel", "reopen", "fee"}),
    )


def make_doc(doc_id, role, fields=(), parser_status=ParserStatus.PARSED, blocking_impact=BlockingImpact.NONE, issued_day=1, issuer="issuer-1", refs=("ADV/01/2026",)):
    return NoticeDocument(
        document_id=doc_id,
        identity=NoticeIdentity(issuer_name="Issuer", issuer_id=issuer, reference_numbers=tuple(refs), title="Research Notice", notice_year=2026),
        source_url=f"https://example.gov/{doc_id}", source_class=SourceClass.ISSUER_PRIMARY,
        document_role=role, parser_status=parser_status, blocking_impact=blocking_impact,
        issued_at=dt(issued_day), published_at=dt(issued_day), retrieved_at=dt(30),
        normalized_text_sha256=f"hash-{doc_id}", fields=tuple(fields),
    )


def assertion(doc_id, field, value, scope=None):
    return FieldAssertion(
        field=field, raw_value=str(value), normalized_value=value,
        scope=scope or Scope(), evidence_text=f"{field.value} is {value}",
        source_document_id=doc_id, extraction_method=ExtractionMethod.MANUAL_FIXTURE,
        grounding=GroundingLevel.EXPLICIT,
    )


def event(event_id, family_id, doc_id, event_type, fields=(), day=1, scope=None, replacement=ReplacementScope.PARTIAL, targets=(), withdraws=(), incorporates=False):
    return GovernanceEvent(
        event_id=event_id, family_id=family_id, source_document_id=doc_id,
        event_type=event_type, affected_fields=frozenset(fields),
        target_scope=scope or Scope(), replacement_scope=replacement,
        issued_at=dt(day), published_at=dt(day), effective_from=dt(day),
        evidence_text=f"event {event_id}", grounding=GroundingLevel.EXPLICIT,
        target_event_ids=tuple(targets), withdraws_event_ids=tuple(withdraws), incorporates_unchanged_fields=incorporates,
    )


def binding(doc_id, family_id="fam-1", strength=BindingStrength.STRONG):
    return FamilyBinding(document_id=doc_id, family_id=family_id, strength=strength, reasons=("test",))

@pytest.fixture
def helpers():
    return {"dt": dt, "make_doc": make_doc, "assertion": assertion, "event": event, "binding": binding}

@pytest.fixture(autouse=True)
def _prevent_real_network_in_all_tests(monkeypatch):
    """No offline test may silently spend search credits or fetch remote evidence."""
    import socket
    socket_module = Path(socket.__file__).resolve()

    def blocked(*_args, **_kwargs):
        raise AssertionError("OFFLINE_TEST_ATTEMPTED_REAL_NETWORK")

    def guarded_connect(sock, address):
        # On Windows, CPython implements socket.socketpair() using a temporary
        # loopback listener and socket.connect().  pytest-asyncio's Proactor
        # event loop needs exactly that stdlib-internal primitive.  Permit it
        # only when its immediate caller is socket.py's socketpair function;
        # direct loopback and every external connection remain denied.
        caller = inspect.currentframe().f_back
        permitted_socketpair = (
            caller is not None
            and caller.f_code.co_name == "socketpair"
            and Path(caller.f_code.co_filename).resolve() == socket_module
            and isinstance(address, tuple)
            and len(address) >= 2
            and address[0] in {"127.0.0.1", "::1"}
        )
        if not permitted_socketpair:
            blocked(sock, address)
        return original_connect(sock, address)

    original_connect = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", blocked)
