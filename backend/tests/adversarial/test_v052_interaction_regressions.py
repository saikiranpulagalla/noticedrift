"""Cross-fix regressions; the failure cases here did not exist in the earlier suite."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from app.domain import (
    BlockingImpact, CriticalField, DocumentRole, EvidenceCoverage,
    EventType, FamilyBinding, BindingStrength, NoticeFamily, ParserStatus,
    ResolutionContext, Scope, ScopeKind, Verdict,
)
from app.domain.resolver import analyze
from app.search import PlannedQuery, QueryPurpose, QueryTier, SearchPlan, SearchExecutor, SearchResponse, SearchMode, SearchStatus
from app.search.models import OrganicResult
from pydantic import ValidationError


F = CriticalField.DEADLINE


def _base(family, helpers):
    d, a, e, b = (helpers[k] for k in ("make_doc", "assertion", "event", "binding"))
    origin = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", F, "2026-10-01")], issued_day=1)
    event = e("decl", family.family_id, "orig", EventType.DECLARES, [F], 1)
    return d, a, e, b, origin, event


def _run(family, helpers, docs, events, bindings, context=None):
    return analyze(family, {F: "2026-10-01"}, docs, events, bindings,
                   context or ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)


def test_later_partial_corrigendum_blocks_changed_even_when_unreadable(family, helpers):
    d, a, e, b, original, declaration = _base(family, helpers)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", F, "2026-10-20")], issued_day=5)
    partial = d("withdraw", DocumentRole.CORRIGENDUM, parser_status=ParserStatus.PARTIAL,
                blocking_impact=BlockingImpact.CONFIRMED_GOVERNING, issued_day=11)
    update = e("ext-event", family.family_id, "ext", EventType.EXTENDS, [F], 5, targets=("decl",))
    result = _run(family, helpers, [original, ext, partial], [declaration, update],
                  [b("orig"), b("ext"), b("withdraw")])
    assert result.verdict == Verdict.UNRESOLVED
    assert "INCOMPLETE_POTENTIAL_GOVERNING_SOURCE" in result.warnings


def test_untrusted_source_not_registered_as_authority_while_other_field_original_survives(family, helpers):
    d, a, e, b, orig, ev0 = _base(family, helpers)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", F, "2026-10-20")], issued_day=5)
    ext = ext.model_copy(update={"source_url": "https://impostor.example/extension"})
    ev1 = e("ext-event", family.family_id, "ext", EventType.EXTENDS, [F], 5, targets=("decl",))
    res = _run(family, helpers, [orig, ext], [ev0, ev1], [b("orig"), b("ext")])
    assert res.verdict == Verdict.UNRESOLVED
    assert "UNVERIFIED_GOVERNING_SOURCE" in res.warnings


def test_partial_applicability_does_not_apply_entire_group(family, helpers):
    d, a, e, b, orig, ev0 = _base(family, helpers)
    scope_b = Scope(kind=ScopeKind.POST, values=("Post B",))
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", F, "2026-10-20")], issued_day=5)
    ev1 = e("ext-event", family.family_id, "ext", EventType.EXTENDS, [F], 5,
            scope=scope_b, targets=("decl",))
    context = ResolutionContext(as_of=helpers["dt"](30), scopes={"POST": ("Post A", "Post B")})
    res = _run(family, helpers, [orig, ext], [ev0, ev1], [b("orig"), b("ext")], context)
    assert res.verdict == Verdict.UNRESOLVED


@pytest.mark.asyncio
async def test_identity_plus_amendment_search_alone_is_partial():
    class Fake:
        async def search(self, query, **kwargs):
            return SearchResponse(query=query, mode=SearchMode.LIVE, status=SearchStatus.OK,
                                  provider_cached=False, captured_at=datetime.now(timezone.utc))
    queries = (
        PlannedQuery(query="identity", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1),
        PlannedQuery(query="corrigendum", purpose=QueryPurpose.AMENDMENT, tier=QueryTier.CORE, priority=1),
    )
    result = await SearchExecutor(Fake()).execute(SearchPlan(queries=queries))
    assert result.coverage == EvidenceCoverage.PARTIAL


@pytest.mark.asyncio
async def test_complete_discovery_types_permit_search_only_adequacy():
    class Fake:
        async def search(self, query, **kwargs):
            return SearchResponse(query=query, mode=SearchMode.LIVE, status=SearchStatus.OK,
                                  provider_cached=False, captured_at=datetime.now(timezone.utc))
    purposes = (QueryPurpose.IDENTITY, QueryPurpose.AMENDMENT, QueryPurpose.EXTENSION, QueryPurpose.CANCELLATION)
    queries = tuple(PlannedQuery(query=p.value, purpose=p, tier=QueryTier.CORE, priority=1) for p in purposes)
    result = await SearchExecutor(Fake()).execute(SearchPlan(queries=queries))
    assert result.coverage == EvidenceCoverage.ADEQUATE
    assert result.attempts == 4


@pytest.mark.asyncio
async def test_interleaved_failure_reuses_single_lock_without_leaking_registry(tmp_path):
    from app.search.cache import LiveSearchCache
    class Fake:
        def __init__(self):
            self.calls = 0
        async def search(self, q, **kwargs):
            self.calls += 1
            await asyncio.sleep(0.002)
            return SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK,
                                  provider_cached=False, captured_at=datetime.now(timezone.utc))
    fake = Fake()
    executor = SearchExecutor(fake, LiveSearchCache(tmp_path))
    q = PlannedQuery(query="same-key", purpose=QueryPurpose.AMENDMENT, tier=QueryTier.CORE, priority=1)
    plan = SearchPlan(queries=(q,))
    results = await asyncio.gather(*(executor.execute(plan, fresh=False, allow_local_cache=True) for _ in range(40)))
    assert fake.calls == 1
    assert all(x.responses[0].status == SearchStatus.OK for x in results)
    assert not executor._locks
    assert not executor._lock_users


@pytest.mark.parametrize("url", ["http://127.1/a", "http://0177.0.0.1/a", "http://0x7f.0.0.1/a"])
def test_ambiguous_ipv4_search_urls_rejected(url):
    with pytest.raises(ValidationError):
        OrganicResult(link=url)


def test_unrecognized_provider_lifecycle_is_not_success():
    from app.search.client import parse_provider_payload
    q = PlannedQuery(query="example", purpose=QueryPurpose.AMENDMENT, tier=QueryTier.CORE, priority=1)
    res = parse_provider_payload({"search_metadata": {"status": "UndocumentedState"},
                                  "organic_results": []}, q, captured=datetime.now(timezone.utc))
    assert res.status == SearchStatus.ERROR
    assert res.error_code == "UNKNOWN_PROVIDER_STATE"


def test_causality_validator_does_not_create_silent_supersession(family, helpers):
    d, a, e, b, orig, ev0 = _base(family, helpers)
    newer = d("ext", DocumentRole.EXTENSION, [a("ext", F, "2026-10-20")], issued_day=10)
    # The event says it was issued *before* its own official source existed.
    bad = e("bad", family.family_id, "ext", EventType.EXTENDS, [F], 5, targets=("decl",))
    res = _run(family, helpers, [orig, newer], [ev0, bad], [b("orig"), b("ext")])
    assert res.verdict == Verdict.UNRESOLVED
    assert "INVALID_GOVERNANCE_EVENT_CONTRACT" in res.warnings


@pytest.mark.asyncio
async def test_duplicate_query_does_not_consume_second_paid_attempt():
    class Fake:
        def __init__(self):
            self.n = 0
        async def search(self, q, **kwargs):
            self.n += 1
            return SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK,
                                  provider_cached=False, captured_at=datetime.now(timezone.utc))
    fake = Fake()
    q = PlannedQuery(query="repeat", purpose=QueryPurpose.AMENDMENT, tier=QueryTier.CORE, priority=1)
    out = await SearchExecutor(fake).execute(SearchPlan(queries=(q, q)))
    assert fake.n == 1
    assert out.attempts == 1
    assert out.coverage == EvidenceCoverage.PARTIAL


def test_unknown_currency_does_not_generate_false_money_drift():
    from app.domain.value_semantics import equivalent, UnsupportedValue
    with pytest.raises(UnsupportedValue, match="CURRENCY_CONTEXT_MISSING"):
        equivalent(CriticalField.FEE, "USD 100", 100)
    with pytest.raises(UnsupportedValue, match="CURRENCY_CONTEXT_MISSING"):
        equivalent(CriticalField.REWARD, 500, "INR 500")
