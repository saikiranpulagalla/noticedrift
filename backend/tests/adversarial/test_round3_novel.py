"""Additional contract tests: new angles distinct from previous report. Not part of release."""
from __future__ import annotations
from datetime import date, datetime, timezone
from dataclasses import replace
import pytest
from app.domain import *
from app.domain.value_semantics import equivalent
from app.domain.normalization import canonicalize_url
from app.domain.resolver import analyze
from app.search import *

F = CriticalField.DEADLINE

def base(family, helpers):
    a,d,e,b = (helpers[k] for k in ("assertion","make_doc","event","binding"))
    orig=d("orig",DocumentRole.ORIGINAL_NOTICE,[a("orig",F,"2026-10-01")],issued_day=1)
    ev0=e("ev0",family.family_id,"orig",EventType.DECLARES,[F],day=1)
    return a,d,e,b,orig,ev0,b("orig")

def run(family,helpers,docs,events,bindings,fields=None):
    return analyze(family,{F:"2026-10-01"} if fields is None else fields,docs,events,bindings,ResolutionContext(as_of=helpers['dt'](30)),EvidenceCoverage.ADEQUATE)


def test_empty_input_cannot_return_positive_assurance(family,helpers):
    a,d,e,b,orig,ev0,b0=base(family,helpers)
    result=run(family,helpers,[orig],[ev0],[b0],fields={})
    assert result.verdict==Verdict.UNRESOLVED


def test_exact_ref_different_year_cannot_strong_bind(family,helpers):
    a,d,e,b,orig,ev0,b0=base(family,helpers)
    newer=d('ext',DocumentRole.EXTENSION,[a('ext',F,'2026-10-22')],issued_day=5)
    newer=newer.model_copy(update={'identity': newer.identity.model_copy(update={'notice_year':2025})})
    event=e('extension','fam-1','ext',EventType.EXTENDS,[F],5,targets=('ev0',))
    out=run(family,helpers,[orig,newer],[ev0,event],[b0,b('ext')])
    assert out.verdict != Verdict.SUPERSEDED


def test_untrusted_unrelated_cycle_must_not_alter_trusted_verdict(family,helpers):
    a,d,e,b,orig,ev0,b0=base(family,helpers)
    outsider=d('ext',DocumentRole.ANNOUNCEMENT,[],issued_day=5)
    loop1=e('loop1','fam-1','ext',EventType.AMENDS,[F],5,targets=('loop2',))
    loop2=e('loop2','fam-1','ext',EventType.AMENDS,[F],5,targets=('loop1',))
    out=run(family,helpers,[orig,outsider],[ev0,loop1,loop2],[b0,b('ext',strength=BindingStrength.POSSIBLE)])
    assert out.verdict==Verdict.SUPPORTED_BY_EVIDENCE


def test_child_cannot_precede_parent_even_if_both_known_at_asof(family,helpers):
    a,d,e,b,orig,ev0,b0=base(family,helpers)
    first=d('ext',DocumentRole.EXTENSION,[a('ext',F,'2026-10-15')],issued_day=10)
    earlier=d('fee',DocumentRole.CORRIGENDUM,[a('fee',F,'2026-10-25')],issued_day=5)
    ev1=e('ev1','fam-1','ext',EventType.EXTENDS,[F],10,targets=('ev0',))
    # This amendment claims to supersede an update that was not yet issued.
    ev2=e('ev2','fam-1','fee',EventType.AMENDS,[F],5,targets=('ev1',))
    out=run(family,helpers,[orig,first,earlier],[ev0,ev1,ev2],[b0,b('ext'),b('fee')])
    assert out.verdict==Verdict.UNRESOLVED


def test_declared_update_missing_affected_fields_must_abstain(family,helpers):
    a,d,e,b,orig,ev0,b0=base(family,helpers)
    changed_doc=d('ext',DocumentRole.EXTENSION,[a('ext',F,'2026-10-20')],issued_day=5)
    # Parsed deadline exists, but extraction forgot affected_fields.
    bad_event=e('ev1','fam-1','ext',EventType.EXTENDS,[],5,targets=('ev0',))
    out=run(family,helpers,[orig,changed_doc],[ev0,bad_event],[b0,b('ext')])
    assert out.verdict==Verdict.UNRESOLVED


def test_date_only_vs_timezone_aware_deadline_require_notice_timezone():
    # At the user venue (India), this instant is the next day.
    date_only=date(2026,10,11)
    utc_instant=datetime(2026,10,10,20,0,tzinfo=timezone.utc)
    assert equivalent(F,date_only,utc_instant)


def test_spa_application_urls_with_different_hash_routes_not_equivalent():
    p='https://example.gov/#/apply/2026/postA'
    q='https://example.gov/#/apply/2026/postB'
    assert not equivalent(CriticalField.APPLICATION_URL,p,q)


def test_currency_metadata_is_required_for_fee_equality(family,helpers):
    a,d,e,b,orig,ev0,b0=base(family,helpers)
    # raw_value says USD, normalized_value mistakenly contains only number.
    fee_source = FieldAssertion(field=CriticalField.FEE,raw_value='USD 100',normalized_value=100,
       evidence_text='Fee USD 100',source_document_id='orig')
    fee_source2 = FieldAssertion(field=CriticalField.FEE,raw_value='INR 100',normalized_value=100,
       evidence_text='Fee INR 100',source_document_id='ext')
    orig2=d('orig',DocumentRole.ORIGINAL_NOTICE,[fee_source],issued_day=1)
    ext=d('ext',DocumentRole.CORRIGENDUM,[fee_source2],issued_day=5)
    ev_fee=e('f0','fam-1','orig',EventType.DECLARES,[CriticalField.FEE],1)
    ev_ext=e('f1','fam-1','ext',EventType.AMENDS,[CriticalField.FEE],5,targets=('f0',))
    out=run(family,helpers,[orig2,ext],[ev_fee,ev_ext],[b('orig'),b('ext')],fields={CriticalField.FEE:100})
    assert out.verdict==Verdict.UNRESOLVED


@pytest.mark.asyncio
async def test_identity_only_search_cannot_claim_complete_amendment_coverage():
    from datetime import datetime,timezone
    class FakeClient:
        async def search(self,planned,**params):
            return SearchResponse(query=planned,mode=SearchMode.LIVE,status=SearchStatus.OK,
                                  captured_at=datetime.now(timezone.utc),provider_cached=False,provider_status='Success')
    q=PlannedQuery(query='"ADV/01/2026"',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
    plan=SearchPlan(queries=(q,),max_calls=8)
    ex=await SearchExecutor(FakeClient()).execute(plan,fresh=True)
    assert ex.coverage!=EvidenceCoverage.ADEQUATE


@pytest.mark.asyncio
async def test_provider_lock_table_does_not_grow_unbounded():
    from datetime import datetime,timezone
    from app.search.executor import SearchExecutor
    class FakeClient:
        async def search(self,planned,**params):
            return SearchResponse(query=planned,mode=SearchMode.LIVE,status=SearchStatus.OK,
                captured_at=datetime.now(timezone.utc),provider_cached=False,provider_status='Success')
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from app.search.cache import LiveSearchCache
    with TemporaryDirectory() as tmp:
        ex=SearchExecutor(FakeClient(),LiveSearchCache(Path(tmp)))
        for i in range(70):
            q=PlannedQuery(query=f'ID-{i}',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
            await ex.execute(SearchPlan(queries=(q,),max_calls=8),fresh=False,allow_local_cache=True)
        assert len(ex._locks)==0


def test_unrelated_bindings_cannot_starve_relevant_binding(family,helpers):
    a,d,e,b,orig,ev0,b0=base(family,helpers)
    foreign=[FamilyBinding(document_id=f'unrelated{i}',family_id='another-family',strength=BindingStrength.STRONG)
             for i in range(81)]
    actual=run(family,helpers,[orig],[ev0],foreign+[b0])
    control=run(family,helpers,[orig],[ev0],[b0]+foreign)
    assert actual.verdict == control.verdict


def test_duplicate_target_lineage_should_be_idempotent(family,helpers):
    a,d,e,b,orig,ev0,b0=base(family,helpers)
    ext=d('ext',DocumentRole.EXTENSION,[a('ext',F,'2026-10-20')],issued_day=5)
    repeated=e('extension','fam-1','ext',EventType.EXTENDS,[F],5,targets=('ev0','ev0'))
    normal=e('extension','fam-1','ext',EventType.EXTENDS,[F],5,targets=('ev0',))
    actual=run(family,helpers,[orig,ext],[ev0,repeated],[b0,b('ext')])
    control=run(family,helpers,[orig,ext],[ev0,normal],[b0,b('ext')])
    assert actual.verdict == control.verdict
