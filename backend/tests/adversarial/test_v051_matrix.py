"""Cross-component semantic and failure-safety matrix for v0.5.1."""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import asyncio
import json
import pytest
from pydantic import ValidationError
from app.domain import *
from app.domain.value_semantics import canonical_value, equivalent, UnsupportedValue
from app.search import *
from app.search.sanitize import sanitize_for_persistence, sanitize_url


@pytest.mark.parametrize("field,a,b", [
    (CriticalField.FEE, 1000, "1000.00"),
    (CriticalField.MIN_AGE, "18", 18),
    (CriticalField.TEAM_SIZE, Decimal("5.0"), 5),
    (CriticalField.LOCATION_MODE, " OnLine ", "online"),
    (CriticalField.APPLICATION_URL, "https://EXAMPLE.com/a?utm_source=x&id=2", "https://example.com/a?id=2"),
    (CriticalField.DEADLINE, "2026-10-01T12:00:00+05:30", "2026-10-01T06:30:00+00:00"),
])
def test_semantic_equivalence_matrix(field, a, b):
    assert equivalent(field, a, b)

@pytest.mark.parametrize("field,value", [
    (CriticalField.FEE, True), (CriticalField.FEE, "₹3 lakh+"),
    (CriticalField.FEE, "NaN"), (CriticalField.DEADLINE, "05/06/2026"),
    (CriticalField.DEADLINE, "2026-10-01T20:00:00"),
    (CriticalField.APPLICATION_URL, "javascript:alert(1)"),
    (CriticalField.LOCATION_MODE, {"online": True}),
    (CriticalField.DEADLINE, None),
])
def test_unsupported_value_abstention(field, value):
    with pytest.raises(UnsupportedValue): canonical_value(field, value)


def test_partial_post_cancellation_scope_applies_only_to_selected_post(family, helpers):
    a,d,e,b = (helpers[x] for x in ("assertion", "make_doc", "event", "binding"))
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")])
    cancel = d("cancel", DocumentRole.CANCELLATION, [], issued_day=5)
    scope = Scope(kind=ScopeKind.POST, values=("Post B",))
    ev = [e("original", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
          e("cancel", "fam-1", "cancel", EventType.CANCELS, [CriticalField.NOTICE_STATUS], 5,
            scope=scope, targets=("original",))]
    def judge(post):
        return analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig,cancel], ev,
                       [b("orig"), b("cancel")],
                       ResolutionContext(as_of=helpers["dt"](30), scopes={"POST": (post,)}),
                       EvidenceCoverage.ADEQUATE).verdict
    assert judge("Post B") == Verdict.CANCELLED
    assert judge("Post A") == Verdict.SUPPORTED_BY_EVIDENCE


def test_issuer_domain_allowlist_overrides_self_described_authority(family, helpers):
    a,d,e,b = (helpers[x] for x in ("assertion", "make_doc", "event", "binding"))
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")])
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-26")], issued_day=5)
    ext = ext.model_copy(update={"source_url": "https://unverified.example/changed"})
    family = family.model_copy(update={"issuer_domains": frozenset({"example.gov"})})
    result = analyze(family, {CriticalField.DEADLINE:"2026-10-01"}, [orig,ext],
                     [e("o", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
                      e("x", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("o",))],
                     [b("orig"), b("ext")], ResolutionContext(as_of=helpers["dt"](30)),
                     EvidenceCoverage.ADEQUATE)
    assert result.verdict != Verdict.SUPERSEDED


def test_unknown_activation_event_not_governing(family, helpers):
    a,d,e,b = (helpers[x] for x in ("assertion", "make_doc", "event", "binding"))
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")])
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-26")])
    ev0 = e("o", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1)
    ev1 = e("x", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("o",))
    ev1 = ev1.model_copy(update={"effective_from": None, "issued_at": None, "published_at": None})
    result = analyze(family, {CriticalField.DEADLINE:"2026-10-01"}, [orig,ext], [ev0,ev1],
                     [b("orig"),b("ext")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert result.verdict != Verdict.SUPERSEDED


def test_effective_until_is_inclusive_and_expires(helpers):
    e = helpers["event"]("e", "f", "orig", EventType.DECLARES, day=1)
    e = e.model_copy(update={"effective_until": helpers["dt"](5)})
    assert e.is_effective(helpers["dt"](5))
    assert not e.is_effective(helpers["dt"](6))
    e = e.model_copy(update={"status": EventStatus.WITHDRAWN})
    assert not e.is_effective(helpers["dt"](3))


def test_scope_empty_unknown_and_normalized(helpers):
    post = Scope(kind=ScopeKind.POST, values=(" Post A ",))
    assert post.applies_to(ResolutionContext(as_of=helpers["dt"](3), scopes={"POST": ("post a",)}))
    assert post.applies_to(ResolutionContext(as_of=helpers["dt"](3))) is None
    assert Scope(kind=ScopeKind.UNKNOWN).applies_to(ResolutionContext(as_of=helpers["dt"](3))) is None
    assert Scope().applies_to(ResolutionContext(as_of=helpers["dt"](3))) is True


def test_replay_exclusive_create_even_on_race(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    q = PlannedQuery(query="x", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    r = SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK,
                       captured_at=datetime.now(timezone.utc))
    store = ReplayEvidenceStore(tmp_path / "replay")
    def put(_):
        try: store.put_once("same", r); return True
        except FileExistsError: return False
    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(put, range(16)))
    assert outcomes.count(True) == 1
    assert store.get("same").mode == SearchMode.REPLAY


def test_cache_age_boundaries_and_bad_envelope(tmp_path):
    t = datetime.now(timezone.utc)
    q = PlannedQuery(query="x", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    r = SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK, captured_at=t)
    cache = LiveSearchCache(tmp_path / "cache", timedelta(minutes=20))
    cache.put("key", r)
    assert cache.get("key", t + timedelta(minutes=20))
    assert cache.get("key", t + timedelta(minutes=21)) is None
    p = tmp_path / "cache" / "key.json"
    p.write_text(json.dumps({"schema": 1, "content": {}}))
    assert cache.get("key", t) is None


def test_search_sanitizer_handles_model_and_url():
    q = PlannedQuery(query="x", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    r = SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.ERROR,
                       captured_at=datetime.now(timezone.utc), error_code="ERROR",
                       error_message="Authorization: Bearer TOKEN987")
    clean = sanitize_for_persistence(r)
    assert "TOKEN987" not in str(clean)
    url = sanitize_url("https://user:pass@example.com/a?access_token=ABC&apikey=DEF&foo=2")
    assert "user:pass" not in url and "ABC" not in url and "DEF" not in url
    assert "foo=2" in url


def test_raw_provider_secret_fields_redacted(tmp_path):
    st = ReplayEvidenceStore(tmp_path / "raw")
    st.put_raw_once("x", {"api_key": "SECRET", "search_metadata": {"error": "secret text"}},
                    captured_at=datetime.now(timezone.utc))
    raw = (tmp_path / "raw" / "x.json").read_text()
    assert "SECRET" not in raw and "secret text" not in raw


def test_provider_results_cannot_pass_private_scheme_or_address():
    from app.search.client import parse_provider_payload
    q = PlannedQuery(query="x", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    r = parse_provider_payload({"organic_results": [{"link": "http://127.0.0.1/x"},
                                                   {"link": "https://ok.example/x"}]}, q,
                               captured=datetime.now(timezone.utc))
    # Unsafe records must not be followed OR silently removed while still
    # presenting the provider response as adequate search coverage.
    assert r.status == SearchStatus.ERROR
    assert r.error_code == 'PROVIDER_RESULTS_REJECTED'
    assert not r.results


@pytest.mark.asyncio
async def test_executor_partial_when_required_query_fails_or_cached():
    class Fake:
        def __init__(self, cached=False, fail=False):
            self.cached,self.fail = cached,fail
        async def search(self,q,**kwargs):
            return SearchResponse(query=q, mode=SearchMode.LIVE,
                                  status=SearchStatus.ERROR if self.fail else SearchStatus.OK,
                                  provider_cached=self.cached,
                                  provider_status="Cached" if self.cached else "Success",
                                  captured_at=datetime.now(timezone.utc))
    q = PlannedQuery(query="a", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    plan = SearchPlan(queries=(q,))
    assert (await SearchExecutor(Fake(fail=True)).execute(plan)).coverage == EvidenceCoverage.PARTIAL
    assert (await SearchExecutor(Fake(cached=True)).execute(plan)).coverage == EvidenceCoverage.PARTIAL
    # Contract v0.5.2: an identity-only search is executed, but not adequate update discovery.
    assert (await SearchExecutor(Fake()).execute(plan)).coverage == EvidenceCoverage.PARTIAL
    assert (await SearchExecutor(Fake()).execute(SearchPlan(queries=()))).coverage == EvidenceCoverage.INSUFFICIENT

@pytest.mark.asyncio
async def test_executor_limits_to_plan_max_two_queries():
    class Fake:
        def __init__(self): self.count=0
        async def search(self, q, **kwargs):
            self.count+=1
            return SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK,
                                  captured_at=datetime.now(timezone.utc))
    fake = Fake()
    queries = tuple(PlannedQuery(query=f"q{i}", purpose=QueryPurpose.IDENTITY,
                                 tier=QueryTier.CORE, priority=i) for i in range(5))
    plan = SearchPlan(queries=queries,max_calls=2)
    result = await SearchExecutor(fake).execute(plan)
    assert result.attempts == fake.count == 2
    assert result.coverage == EvidenceCoverage.PARTIAL
    with pytest.raises(ValueError):
        await SearchExecutor(fake).execute(SearchPlan(queries=queries,max_calls=9))


def test_search_plan_localization_frozen_with_supplied_dict():
    plan = SearchPlan(queries=(), localization={"hl":"en", "gl":"in"})
    with pytest.raises(TypeError): plan.localization["gl"]="us"
    assert dict(plan.localization)=={"gl":"in", "hl":"en"}


def test_invalid_search_urls_rejected():
    from app.search.models import OrganicResult
    for url in ("javascript:alert(1)","data:text/html,test", "file:///tmp/x",
                "https://admin:password@example.com", "http://192.168.0.1"):
        with pytest.raises(ValidationError):
            OrganicResult(link=url)


def test_analysis_rejects_oversized_event_list_before_building_graph(family, helpers):
    d,a,e,b = (helpers[x] for x in ("make_doc", "assertion", "event", "binding"))
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE,[a("orig",CriticalField.DEADLINE,"2026-10-01")])
    events = [e(f"ev{i}","fam-1","orig",EventType.DECLARES,[CriticalField.DEADLINE],1) for i in range(161)]
    result = analyze(family, {CriticalField.DEADLINE:"2026-10-01"}, [orig], events, [b("orig")],
                     ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert result.verdict == Verdict.UNRESOLVED
    assert "EVIDENCE_BUDGET_EXCEEDED" in result.warnings
