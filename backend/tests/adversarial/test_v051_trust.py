"""Regression probes from two pre-release adversarial audits.

These enter the public model, resolver, transport, and storage boundaries directly;
there is no adapter-side filtering hiding the malformed inputs.
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import pytest
import httpx
from pydantic import ValidationError
from app.domain import *
from app.domain.value_semantics import equivalent, UnsupportedValue
from app.search import *
from app.search.client import parse_provider_payload

F = CriticalField.DEADLINE

def scenario(family, helpers, *, extension=True):
    a,d,e,b = (helpers[n] for n in ("assertion", "make_doc", "event", "binding"))
    docs = [d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", F, "2026-10-01")])]
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [F], 1)]
    if extension:
        docs.append(d("ext", DocumentRole.EXTENSION, [a("ext", F, "2026-10-20")], issued_day=5))
        events.append(e("ev1", "fam-1", "ext", EventType.EXTENDS, [F], 5, targets=("ev0",)))
    binds = [b(x.document_id) for x in docs]
    return docs, events, binds

def decide(family, helpers, docs, events, binds, input_value="2026-10-01", *, scope=None, as_of=30):
    return analyze(family, {F: input_value}, docs, events, binds,
                   ResolutionContext(as_of=helpers["dt"](as_of), scopes=scope or {}), EvidenceCoverage.ADEQUATE)

@pytest.mark.parametrize("strength", [BindingStrength.POSSIBLE, BindingStrength.REJECTED])
def test_weak_and_rejected_withdrawals_cannot_govern(family, helpers, strength):
    docs, events, binds = scenario(family, helpers)
    d,e,b = (helpers[n] for n in ("make_doc", "event", "binding"))
    docs += [d("withdraw", DocumentRole.CORRIGENDUM, issued_day=10)]
    events += [e("wd", "fam-1", "withdraw", EventType.WITHDRAWS, day=10, withdraws=("ev1",))]
    binds += [b("withdraw", strength=strength)]
    assert decide(family, helpers, docs, events, binds).verdict == Verdict.SUPERSEDED

def test_scoped_withdrawal_does_not_apply_elsewhere(family, helpers):
    docs, events, binds = scenario(family, helpers)
    d,e,b = (helpers[n] for n in ("make_doc", "event", "binding"))
    docs += [d("withdraw", DocumentRole.CORRIGENDUM, issued_day=10)]
    events += [e("wd", "fam-1", "withdraw", EventType.WITHDRAWS, day=10,
                 scope=Scope(kind=ScopeKind.POST, values=("Post B",)), withdraws=("ev1",))]
    binds += [b("withdraw")]
    assert decide(family, helpers, docs, events, binds, scope={"POST": ("Post A",)}).verdict == Verdict.SUPERSEDED
    assert decide(family, helpers, docs, events, binds, scope={"POST": ("post b",)}).verdict == Verdict.SUPPORTED_BY_EVIDENCE

def test_withdrawal_of_withdrawal_restores_extension(family, helpers):
    docs, events, binds = scenario(family, helpers)
    d,e,b = (helpers[n] for n in ("make_doc", "event", "binding"))
    for name, day in (("withdraw", 10), ("fee", 11)):
        docs += [d(name, DocumentRole.CORRIGENDUM, issued_day=day)]
        binds += [b(name)]
    events += [e("wd1", "fam-1", "withdraw", EventType.WITHDRAWS, day=10, withdraws=("ev1",)),
               e("wd2", "fam-1", "fee", EventType.WITHDRAWS, day=11, withdraws=("wd1",))]
    assert decide(family, helpers, docs, events, binds).verdict == Verdict.SUPERSEDED

def test_aggregator_even_if_binding_claims_strong_cannot_govern(family, helpers):
    docs, events, binds = scenario(family, helpers)
    docs[1] = docs[1].model_copy(update={"source_class": SourceClass.AGGREGATOR})
    assert decide(family, helpers, docs, events, binds).verdict != Verdict.SUPERSEDED

def test_announcement_cannot_govern_extension(family, helpers):
    docs, events, binds = scenario(family, helpers)
    docs[1] = docs[1].model_copy(update={"document_role": DocumentRole.ANNOUNCEMENT})
    assert decide(family, helpers, docs, events, binds).verdict != Verdict.SUPERSEDED

@pytest.mark.parametrize("status", [ParserStatus.PARTIAL, ParserStatus.FAILED, ParserStatus.UNSUPPORTED])
def test_broken_parser_cannot_produce_definitive_verdict(family, helpers, status):
    docs, events, binds = scenario(family, helpers)
    docs[1] = docs[1].model_copy(update={"parser_status": status})
    assert decide(family, helpers, docs, events, binds).verdict == Verdict.UNRESOLVED

def test_reference_blanks_not_exact_match(family, helpers):
    doc = helpers["make_doc"]("orig", DocumentRole.ORIGINAL_NOTICE, refs=("",))
    fam = family.model_copy(update={"reference_aliases": frozenset({""})})
    assert bind_document(doc, fam).strength != BindingStrength.STRONG

def test_assertion_document_provenance_cannot_be_forged(helpers):
    d,a = helpers["make_doc"],helpers["assertion"]
    with pytest.raises(ValidationError, match="FIELD_SOURCE_MISMATCH"):
        d("orig", DocumentRole.ORIGINAL_NOTICE, [a("other", F, "2026-10-05")])

def test_model_copy_bypass_stopped_at_analysis(family, helpers):
    docs, events, binds = scenario(family, helpers)
    docs[1] = docs[1].model_copy(update={"fields": (helpers["assertion"]("other", F, "2099-01-01"),)})
    assert decide(family, helpers, docs, events, binds).verdict == Verdict.UNRESOLVED

def test_duplicate_ids_rejected_at_boundary(family, helpers):
    docs,events,binds = scenario(family, helpers)
    assert decide(family, helpers, docs + [docs[-1]], events, binds).verdict == Verdict.UNRESOLVED
    assert decide(family, helpers, docs, events + [events[-1]], binds).verdict == Verdict.UNRESOLVED
    assert decide(family, helpers, docs, events, binds + [binds[-1]]).verdict == Verdict.UNRESOLVED

def test_same_time_event_lineage_independent_of_id(family, helpers):
    docs, events, binds = scenario(family, helpers)
    events[0] = events[0].model_copy(update={"event_id": "z-parent", "effective_from": helpers["dt"](5)})
    events[1] = events[1].model_copy(update={"event_id": "a-child", "target_event_ids": ("z-parent",)})
    assert decide(family, helpers, docs, events, binds).verdict == Verdict.SUPERSEDED

def test_future_issued_without_effective_date_does_not_apply(family, helpers):
    docs, events, binds = scenario(family, helpers)
    events[1] = events[1].model_copy(update={"issued_at": helpers["dt"](20),
                                              "published_at": helpers["dt"](20), "effective_from": None})
    assert decide(family, helpers, docs, events, binds, as_of=10).verdict == Verdict.SUPPORTED_BY_EVIDENCE

def test_invalid_datetime_models_rejected(helpers):
    e = helpers["event"]("a", "fam-1", "orig", EventType.DECLARES)
    with pytest.raises(ValidationError):
        GovernanceEvent.model_validate(e.model_copy(update={"effective_from": datetime(2026, 10, 1)}).model_dump())
    with pytest.raises(ValidationError):
        GovernanceEvent.model_validate(e.model_copy(update={"effective_until": helpers["dt"](1),
                                                     "effective_from": helpers["dt"](10)}).model_dump())

def test_date_value_semantics_never_false_supersede(family, helpers):
    docs,events,binds = scenario(family, helpers, extension=False)
    docs[0] = helpers["make_doc"]("orig", DocumentRole.ORIGINAL_NOTICE,
                                   [helpers["assertion"]("orig", F, date(2026,10,1))])
    assert decide(family, helpers, docs, events, binds, "2026-10-01").verdict == Verdict.SUPPORTED_BY_EVIDENCE
    assert equivalent(F, "2026-10-01", "2026-10-01T23:59:00+05:30")
    assert not equivalent(F, "2026-10-01", "2026-10-02")

def test_no_nested_mutability(helpers):
    from app.search import SearchPlan
    ctx = ResolutionContext(as_of=helpers["dt"](5), scopes={"POST": ("Post A",)})
    with pytest.raises(TypeError): ctx.scopes["POST"] = ("Post B",)
    plan = SearchPlan(queries=())
    with pytest.raises(TypeError): plan.localization["gl"] = "us"
    with pytest.raises(ValidationError):
        FieldAssertion(field=F, raw_value="x", normalized_value={"evil": "dict"},
                       evidence_text="x", source_document_id="d")

def test_url_and_unicode_canonicalization():
    from app.domain.normalization import normalize_reference, canonicalize_url
    assert normalize_reference("ＡＤＶ／０１／２０２６") == "ADV/01/2026"
    assert normalize_reference("ADV\u200b/01/2026") == "ADV/01/2026"
    assert canonicalize_url("https://example.com/a//b") != canonicalize_url("https://example.com/a/b")
    with pytest.raises(ValueError): canonicalize_url("https://user:secret@example.com/x")

def test_replay_rejects_path_traversal_and_tampering(tmp_path):
    store = ReplayEvidenceStore(tmp_path / "replay")
    q = PlannedQuery(query="test", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    t = datetime.now(timezone.utc)
    resp = SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK, captured_at=t)
    with pytest.raises(ValueError): store.put_once("../escape", resp)
    store.put_once("safe", resp)
    assert store.get("safe").mode == SearchMode.REPLAY
    path = tmp_path / "replay" / "safe.json"
    data = json.loads(path.read_text())
    data["content"]["mode"] = "ERROR"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="EVIDENCE_TAMPERED"):
        store.get("safe")

def test_replay_raw_uses_provider_parser(tmp_path):
    store = ReplayEvidenceStore(tmp_path / "replay")
    t = datetime.now(timezone.utc)
    raw = {"search_metadata": {"status": "Cached", "id": "sid"},
           "organic_results": [{"link": "https://example.gov/notice"}]}
    store.put_raw_once("raw", raw, captured_at=t)
    captured = store.get_raw("raw")
    q = PlannedQuery(query="test", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    r = parse_provider_payload(captured["payload"], q, captured=t, mode=SearchMode.REPLAY)
    assert r.status == SearchStatus.OK and r.provider_cached and r.mode == SearchMode.REPLAY

def test_live_cache_corrupt_future_and_modes(tmp_path):
    cache = LiveSearchCache(tmp_path / "cache")
    t = datetime.now(timezone.utc)
    q = PlannedQuery(query="test", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    cache.put("safe", SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK, captured_at=t))
    assert cache.get("safe", t).mode == SearchMode.LIVE_CACHE
    assert cache.get("safe", t - timedelta(hours=2)) is None
    (tmp_path / "cache" / "safe.json").write_text("invalid JSON")
    assert cache.get("safe", t) is None
    with pytest.raises(ValueError): cache.get("../bad", t)

@pytest.mark.asyncio
async def test_serpapi_fresh_request_and_schema_and_provider_cache():
    async def handler(request):
        assert request.url.params.get("no_cache") == "true"
        return httpx.Response(200, json={"search_metadata": {"status": "Cached", "id": "abc"},
                                         "organic_results": [{"link": "javascript:alert(1)"},
                                                             {"link": "https://example.gov/x"}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    q = PlannedQuery(query="x", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    r = await SerpApiClient("SECRET", client=client).search(q)
    assert r.provider_cached is True and r.mode == SearchMode.LIVE
    assert r.status == SearchStatus.ERROR
    assert r.error_code == 'PROVIDER_RESULTS_REJECTED'
    assert not r.results
    assert "SECRET" not in r.model_dump_json()
    assert dict(r.request_parameters)["no_cache"] == "true"
    await client.aclose()

@pytest.mark.parametrize("payload", [[1,2], {"organic_results": "wrong"},
                                      {"organic_results": ["bad"]}, {"search_metadata": []}])
def test_malformed_provider_json_structured(payload):
    q = PlannedQuery(query="x", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    r = parse_provider_payload(payload, q, captured=datetime.now(timezone.utc))
    assert r.status == SearchStatus.ERROR and r.error_code == "INVALID_SCHEMA"

def test_upstream_error_never_exposes_secret():
    q = PlannedQuery(query="x", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    r = parse_provider_payload({"error": "api_key=SECRET123"}, q, captured=datetime.now(timezone.utc))
    assert "SECRET123" not in r.model_dump_json()

def test_query_operator_injection_is_escaped():
    p = plan_queries(reference_number='ABC" site:evil.example "', issuer_name="issuer", title="test",
                     official_domain="gov.in OR site:evil.example")
    # An operator-bearing identifier must be rejected instead of silently
    # rewritten into a *different* identifier that might certify freshness.
    assert p.queries == ()

@pytest.mark.asyncio
async def test_executor_never_exceeds_eight_provider_calls():
    class Fake:
        def __init__(self): self.calls = 0
        async def search(self, q, **kwargs):
            self.calls += 1
            return SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK,
                                  captured_at=datetime.now(timezone.utc))
    fake = Fake()
    queries = tuple(PlannedQuery(query=f"q{i}", purpose=QueryPurpose.IDENTITY,
                                 tier=QueryTier.CORE, priority=i) for i in range(100))
    outcome = await SearchExecutor(fake).execute(SearchPlan(queries=queries, max_calls=8))
    assert fake.calls == outcome.attempts == 8

@pytest.mark.asyncio
async def test_identical_simultaneous_cache_misses_singleflight(tmp_path):
    class Fake:
        def __init__(self): self.calls = 0
        async def search(self, q, **kwargs):
            self.calls += 1
            await asyncio.sleep(0.01)
            return SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK,
                                  captured_at=datetime.now(timezone.utc))
    fake = Fake()
    executor = SearchExecutor(fake, LiveSearchCache(tmp_path / "cache"))
    q = PlannedQuery(query="same", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    plan = SearchPlan(queries=(q,))
    await asyncio.gather(*(executor.execute(plan, fresh=False, allow_local_cache=True) for _ in range(25)))
    assert fake.calls == 1
