from datetime import date, datetime, timezone
import pytest
from pydantic import ValidationError
from app.domain import *
from app.search import *
from app.domain.normalization import canonicalize_url
from app.domain.value_semantics import canonical_value, UnsupportedValue
from app.domain.resolver import _build_active_event_set, resolve_field

F = CriticalField.DEADLINE

def basic(helpers):
    d,a,e,b = (helpers[x] for x in ("make_doc", "assertion", "event", "binding"))
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", F, "2026-10-01")])
    return orig, e("ev0", "fam-1", "orig", EventType.DECLARES, [F], 1), b("orig")

def run(family,helpers,docs,events,binds,inputs=None):
    return analyze(family, inputs or {F:"2026-10-01"}, docs, events, binds,
                   ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)

def test_missing_governing_source_id_abstains(family,helpers):
    doc,e,b=basic(helpers)
    ghost=helpers["event"]("ghost", "fam-1", "missing", EventType.EXTENDS, [F], 10, targets=("ev0",))
    r=run(family,helpers,[doc],[e,ghost],[b])
    assert r.verdict == Verdict.UNRESOLVED and "EVENT_SOURCE_NOT_FOUND" in r.warnings

def test_empty_withdrawal_and_missing_target_abstain(family,helpers):
    doc,e,b=basic(helpers)
    d=helpers["make_doc"]("withdraw",DocumentRole.CORRIGENDUM,issued_day=10)
    w=helpers["event"]("w", "fam-1", "withdraw", EventType.WITHDRAWS,day=10)
    assert run(family,helpers,[doc,d],[e,w],[b,helpers["binding"]("withdraw")]).verdict==Verdict.UNRESOLVED
    w2=w.model_copy(update={"withdraws_event_ids":("never-existed",)})
    assert run(family,helpers,[doc,d],[e,w2],[b,helpers["binding"]("withdraw")]).verdict==Verdict.UNRESOLVED

def test_cyclic_events_abstain(family,helpers):
    d,a,e,b=(helpers[x] for x in ("make_doc", "assertion", "event", "binding"))
    orig,ev0,b0=basic(helpers)
    ext=d("ext",DocumentRole.EXTENSION,[a("ext",F,"2026-10-30")],issued_day=5)
    ev1=e("ev1","fam-1","ext",EventType.EXTENDS,[F],5,targets=("ev2",))
    ev2=e("ev2","fam-1","ext",EventType.EXTENDS,[F],5,targets=("ev1",))
    assert run(family,helpers,[orig,ext],[ev0,ev1,ev2],[b0,b("ext")]).verdict==Verdict.UNRESOLVED

def test_invalid_parent_value_abstains(family,helpers):
    d,a,e,b=(helpers[x] for x in ("make_doc", "assertion", "event", "binding"))
    orig=d("orig",DocumentRole.ORIGINAL_NOTICE,[a("orig",F,"tomorrow")])
    ext=d("ext",DocumentRole.EXTENSION,[a("ext",F,"2026-10-30")],issued_day=5)
    ev0=e("ev0","fam-1","orig",EventType.DECLARES,[F],1)
    ev1=e("ev1","fam-1","ext",EventType.EXTENDS,[F],5,targets=("ev0",))
    assert run(family,helpers,[orig,ext],[ev0,ev1],[b("orig"),b("ext")]).verdict==Verdict.UNRESOLVED

def test_ambiguous_input_value_abstains(family,helpers):
    doc,ev,b=basic(helpers)
    r=run(family,helpers,[doc],[ev],[b],{F:"05/06/26"})
    assert r.verdict == Verdict.UNRESOLVED

def test_multiple_explicit_declarations_create_conflict(family,helpers):
    d,a=helpers["make_doc"],helpers["assertion"]
    doc=d("orig",DocumentRole.ORIGINAL_NOTICE,[a("orig",F,"2026-10-01"),a("orig",F,"2026-10-02")])
    ev=helpers["event"]("ev0","fam-1","orig",EventType.DECLARES,[F],1)
    assert run(family,helpers,[doc],[ev],[helpers["binding"]("orig")]).verdict == Verdict.CONFLICT

def test_full_replacement_conflicting_explicit_values(family,helpers):
    d,a,e,b=(helpers[x] for x in ("make_doc", "assertion", "event", "binding"))
    orig,ev0,b0=basic(helpers)
    repl=d("ext",DocumentRole.REVISED_NOTICE,[a("ext",F,"2026-10-20"),a("ext",F,"2026-10-25")],issued_day=5)
    event=e("revised","fam-1","ext",EventType.SUPERSEDES,[F],5,
            targets=("ev0",),replacement=ReplacementScope.FULL)
    assert run(family,helpers,[orig,repl],[ev0,event],[b0,b("ext")]).verdict==Verdict.CONFLICT

def test_second_level_link_through_unrelated_field_update(family,helpers):
    d,a,e,b=(helpers[x] for x in ("make_doc", "assertion", "event", "binding"))
    orig,ev0,b0=basic(helpers)
    fee=d("fee",DocumentRole.CORRIGENDUM,[a("fee",CriticalField.FEE,0)],issued_day=5)
    ext=d("ext",DocumentRole.EXTENSION,[a("ext",F,"2026-10-20")],issued_day=10)
    fee_event=e("f","fam-1","fee",EventType.AMENDS,[CriticalField.FEE],5,targets=("ev0",))
    extension_event=e("x","fam-1","ext",EventType.EXTENDS,[F],10,targets=("f",))
    assert run(family,helpers,[orig,fee,ext],[ev0,fee_event,extension_event],[b0,b("fee"),b("ext")]).verdict==Verdict.SUPERSEDED

def test_withdrawal_older_than_target_abstains(family,helpers):
    d,a,e,b=(helpers[x] for x in ("make_doc", "assertion", "event", "binding"))
    orig,ev0,b0=basic(helpers)
    ext=d("ext",DocumentRole.EXTENSION,[a("ext",F,"2026-10-25")],issued_day=10)
    wd=d("withdraw",DocumentRole.CORRIGENDUM,issued_day=5)
    ev1=e("e","fam-1","ext",EventType.EXTENDS,[F],10,targets=("ev0",))
    w=e("wd","fam-1","withdraw",EventType.WITHDRAWS,day=5,withdraws=("e",))
    assert run(family,helpers,[orig,ext,wd],[ev0,ev1,w],[b0,b("ext"),b("withdraw")]).verdict==Verdict.UNRESOLVED

def test_naive_context_and_scope_malformed_rejected(helpers):
    with pytest.raises(ValidationError): ResolutionContext(as_of=datetime(2026,10,1))
    with pytest.raises(ValidationError): ResolutionContext(as_of=helpers["dt"](1),scopes="wrong")
    with pytest.raises(ValueError): canonicalize_url("https://example.com:5000/x")


def test_missing_replay_or_raw_returns_none(tmp_path):
    store=ReplayEvidenceStore(tmp_path / "replay")
    assert store.get("missing") is None
    assert store.get_raw("missing") is None


def test_unrecognized_raw_fixture_rejected(tmp_path):
    from app.search.cache import ReplayEvidenceStore
    st=ReplayEvidenceStore(tmp_path / "r")
    q=PlannedQuery(query="q", purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=1)
    r=SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK,
                     captured_at=datetime.now(timezone.utc))
    st.put_once("key",r)
    with pytest.raises(ValueError): st.get_raw("key")
    st.put_raw_once("raw",{"organic_results":[]},captured_at=datetime.now(timezone.utc))
    with pytest.raises(ValueError): st.get("raw")


def test_normalization_invalid_url_rejected():
    for url in ("ftp://example.com/a", "https://", "file:///tmp/a"):
        with pytest.raises(ValueError): canonicalize_url(url)

@pytest.mark.asyncio
async def test_search_executor_records_pinned_location_and_no_cache():
    from app.search import SearchExecutor, SearchPlan, PlannedQuery, QueryPurpose, QueryTier
    class Fake:
        def __init__(self): self.kw = None
        async def search(self, q, **kwargs):
            self.kw = kwargs
            return SearchResponse(query=q, mode=SearchMode.LIVE, status=SearchStatus.OK,
                                  provider_cached=False, provider_status="Success",
                                  captured_at=datetime.now(timezone.utc))
    client = Fake()
    q = PlannedQuery(query="x",purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
    plan = SearchPlan(queries=(q,), localization={"gl":"in", "hl":"en", "location":"Hyderabad, Telangana, India"})
    run = await SearchExecutor(client).execute(plan)
    assert client.kw["location"] == "Hyderabad, Telangana, India"
    assert client.kw["no_cache"] is True
    # Identity-only search cannot establish that corrigenda/cancellations were checked.
    assert run.coverage == EvidenceCoverage.PARTIAL


def test_search_plan_rejects_malformed_domain_without_crashing():
    from app.search import plan_queries
    for domain in ("bad.example:9999999999", "evil.example/foo", "gov.in OR site:fake.example"):
        plan = plan_queries(reference_number="ADV/01/2026",issuer_name="Issuer",title=None,
                            official_domain=domain)
        assert not any(q.use_advanced_operators for q in plan.queries)


def test_field_comparison_unknown_numeric_rejected():
    from app.domain.value_semantics import canonical_value, UnsupportedValue
    with pytest.raises(UnsupportedValue):
        canonical_value(CriticalField.REWARD, "infinity")
    with pytest.raises(UnsupportedValue):
        canonical_value(CriticalField.APPLICATION_URL, "https://bad.example:1234/path")


def test_replay_and_local_cache_do_not_share_mode(tmp_path):
    from app.search import ReplayEvidenceStore, LiveSearchCache, PlannedQuery, QueryPurpose, QueryTier
    now = datetime.now(timezone.utc)
    q = PlannedQuery(query="x",purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
    result = SearchResponse(query=q, mode=SearchMode.LIVE,status=SearchStatus.OK,captured_at=now)
    local = LiveSearchCache(tmp_path/"local")
    replay = ReplayEvidenceStore(tmp_path/"replay")
    local.put("key",result)
    replay.put_once("key",result)
    assert local.get("key",now).mode == SearchMode.LIVE_CACHE
    assert replay.get("key").mode == SearchMode.REPLAY


def test_typed_value_rejects_ambiguous_datetime_and_unsupported_nonstring():
    from app.domain.value_semantics import canonical_value, UnsupportedValue
    assert canonical_value(CriticalField.DEADLINE, datetime(2026,10,1,12,tzinfo=timezone.utc))[0] == "deadline_instant"
    with pytest.raises(UnsupportedValue):
        canonical_value(CriticalField.DEADLINE, datetime(2026,10,1,12))
    with pytest.raises(UnsupportedValue):
        canonical_value(CriticalField.DEADLINE, 20261001)
    with pytest.raises(UnsupportedValue):
        canonical_value(CriticalField.LOCATION_MODE, 42)
