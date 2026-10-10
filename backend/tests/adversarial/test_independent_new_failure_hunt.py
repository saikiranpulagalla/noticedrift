"""Independent release-blocking red-team tests for NoticeDrift v0.5.1.
These tests intentionally FAIL on the audited release. Not part of the shipped ZIP.
"""
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from app.domain import *
from app.domain.resolver import analyze
from app.search.client import parse_provider_payload
from app.search.models import OrganicResult
from app.search.models import PlannedQuery, QueryPurpose, QueryTier, SearchStatus
from app.search.sanitize import sanitize_for_persistence

F = CriticalField.DEADLINE


def common(family, helpers):
    d,a,e,b=(helpers[k] for k in ('make_doc','assertion','event','binding'))
    docs = [d('orig', DocumentRole.ORIGINAL_NOTICE,[a('orig',F,'2026-10-01')]),
            d('ext', DocumentRole.EXTENSION,[a('ext',F,'2026-10-15')],issued_day=5)]
    evs = [e('o','fam-1','orig',EventType.DECLARES,[F],1),
           e('x','fam-1','ext',EventType.EXTENDS,[F],5,targets=('o',))]
    bs = [b('orig'),b('ext')]
    return docs,evs,bs


def decide(family,helpers,docs,events,binds,scopes=None,as_of=20):
    return analyze(family,{F:'2026-10-01'},docs,events,binds,
       ResolutionContext(as_of=helpers['dt'](as_of),scopes=scopes or {}),EvidenceCoverage.ADEQUATE)


def test_relevant_partial_later_source_blocks_prior_superseded(family,helpers):
    docs,evs,bs=common(family,helpers)
    docs.append(helpers['make_doc']('withdraw',DocumentRole.CORRIGENDUM,
         parser_status=ParserStatus.PARTIAL,blocking_impact=BlockingImpact.CONFIRMED_GOVERNING,issued_day=12))
    bs.append(helpers['binding']('withdraw'))
    assert decide(family,helpers,docs,evs,bs).verdict == Verdict.UNRESOLVED


def test_relevant_partial_reopening_blocks_prior_cancellation(family,helpers):
    docs,evs,bs=common(family,helpers)
    docs += [helpers['make_doc']('cancel',DocumentRole.CANCELLATION,issued_day=8),
             helpers['make_doc']('reopen',DocumentRole.REOPENING,
                parser_status=ParserStatus.PARTIAL,blocking_impact=BlockingImpact.CONFIRMED_GOVERNING,issued_day=12)]
    evs += [helpers['event']('ce','fam-1','cancel',EventType.CANCELS,day=8,targets=('o',))]
    bs += [helpers['binding']('cancel'),helpers['binding']('reopen')]
    assert decide(family,helpers,docs,evs,bs).verdict == Verdict.UNRESOLVED


def test_event_may_not_govern_before_source_document_exists(family,helpers):
    docs,evs,bs=common(family,helpers)
    docs[1]=helpers['make_doc']('ext',DocumentRole.EXTENSION,[helpers['assertion']('ext',F,'2026-10-15')],issued_day=25)
    assert decide(family,helpers,docs,evs,bs,as_of=10).verdict != Verdict.SUPERSEDED


def test_provider_error_status_must_not_be_success():
    q=__import__('app.search',fromlist=['PlannedQuery']).PlannedQuery(query='q',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
    r=parse_provider_payload({'search_metadata':{'status':'Error'},'organic_results':[]},q,captured=datetime.now(timezone.utc))
    assert r.status == SearchStatus.ERROR


def test_provider_processing_status_must_not_be_completed():
    q=PlannedQuery(query='q',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
    r=parse_provider_payload({'search_metadata':{'status':'Processing'},'organic_results':[]},q,captured=datetime.now(timezone.utc))
    assert r.status != SearchStatus.OK


def test_provider_successful_empty_results_may_have_error_message():
    q=PlannedQuery(query='q',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
    r=parse_provider_payload({'search_metadata':{'status':'Success'},'organic_results':[],
         'search_information':{'organic_results_state':'Fully empty'},
         'error':"Google hasn't returned any results for this query."},q,captured=datetime.now(timezone.utc))
    assert r.status == SearchStatus.OK


def test_empty_scoped_selector_abstains(helpers):
    s=Scope(kind=ScopeKind.POST,values=())
    assert s.applies_to(ResolutionContext(as_of=helpers['dt'](20),scopes={'POST':('A',)})) is None


def test_scope_items_direct_constructor_canonicalizes(helpers):
    s=Scope(kind=ScopeKind.POST,values=('Post A',))
    assert s.applies_to(ResolutionContext(as_of=helpers['dt'](20),scope_items=(('POST',('Post A',)),))) is True


def test_multiple_posts_cannot_automatically_receive_subset_update(family,helpers):
    docs,evs,bs=common(family,helpers)
    evs[1]=evs[1].model_copy(update={'target_scope':Scope(kind=ScopeKind.POST,values=('Post B',))})
    assert decide(family,helpers,docs,evs,bs,scopes={'POST':('Post A','Post B')}).verdict == Verdict.UNRESOLVED


def test_unverified_caller_primary_label_insufficient_for_attacker_host(family,helpers):
    docs,evs,bs=common(family,helpers)
    docs[1]=docs[1].model_copy(update={'source_url':'https://attacker.example/corrigendum'})
    assert decide(family,helpers,docs,evs,bs).verdict == Verdict.UNRESOLVED


def test_sanitizer_removes_api_keys_in_embedded_url_strings():
    text='SerpApi returned for https://serpapi.com/search.json?api_key=TEST_SECRET123'
    assert 'TEST_SECRET123' not in sanitize_for_persistence(text)


@pytest.mark.parametrize('url',['http://2130706433/x','http://0x7f000001/x','http://017700000001/x'])
def test_numeric_localhost_forms_cannot_pass_search_url_admission(url):
    with pytest.raises(ValidationError):
        OrganicResult(link=url)


def test_all_rejected_organic_results_not_considered_complete_success():
    q=PlannedQuery(query='q',purpose=QueryPurpose.IDENTITY,tier=QueryTier.CORE,priority=1)
    r=parse_provider_payload({'search_metadata':{'status':'Success'},
                              'organic_results':[{'link':'javascript:alert(1)'}]},q,captured=datetime.now(timezone.utc))
    assert r.status != SearchStatus.OK
