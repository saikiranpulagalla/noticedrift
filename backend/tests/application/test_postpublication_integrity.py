"""Self-contained R4-R8 cross-checks. Fictional bytes and transports only."""
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.api.main import create_app
from app.application.models import NoticeCheckRequest
from app.sources import AuthorityAttestation, IssuerAuthorityRegistry, SnapshotStore
from app.search.sanitize import sanitize_for_persistence
from app.sources.fetch import safe_target
from app.sources.models import SourceFailure
from test_v07_workflow import workflow, request, ORIGINAL, UPDATE, ORIG_HTML, UPDATE_HTML, CANCEL_HTML

RELATION = b'The deadline is extended from 01 October 2026 to 26 October 2026.'


async def outcome(body, *, original=ORIG_HTML, req=None):
    engine, search, transport = workflow([ORIGINAL, UPDATE], {ORIGINAL: original, UPDATE: body})
    out = await engine.check(req or request())
    print('WORKFLOW', out.analysis.verdict.value, out.analysis.coverage.value,
          out.warnings, len(out.sources), len(search.calls), len(transport.calls))
    return out


@pytest.mark.asyncio
@pytest.mark.parametrize('qualifier', [
    'Only candidates applying for Zone 4 positions may use this extended deadline.',
    'The extension shall become operative only after approval from the board.',
    'The cancellation has been stayed by the court.',
])
@pytest.mark.parametrize('placement', ['before', 'after', 'distant', 'footer'])
async def test_r4_01_unsupported_operativity(qualifier, placement):
    body = CANCEL_HTML if 'cancellation' in qualifier else UPDATE_HTML
    addition = ('<p>' + qualifier + '</p>').encode()
    if placement == 'before': body = body.replace(b'<h1>', addition + b'<h1>')
    elif placement == 'footer': body = body.replace(b'</main>', b'<footer>' + qualifier.encode() + b'</footer></main>')
    else: body = body.replace(b'</main>', (b'<p>Administrative information.</p>' * (3 if placement == 'distant' else 0)) + addition + b'</main>')
    out = await outcome(body)
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert out.analysis.coverage.value == 'INSUFFICIENT'


@pytest.mark.asyncio
@pytest.mark.parametrize('outer', [
    '<header>Applicable exclusively to Zone 4 candidates.</header>{}',
    '{}<main>This cancellation has been stayed by the court.</main>',
    '{}<article>Applicable exclusively to Zone 4 candidates.</article>',
    '<main></main>{}',
])
async def test_r4_02_outside_selected_region(outer):
    out = await outcome(outer.format(UPDATE_HTML.decode()).encode())
    assert out.analysis.verdict.value == 'UNRESOLVED'


@pytest.mark.asyncio
@pytest.mark.parametrize('container', ['select', 'datalist', 'textarea'])
async def test_r4_03_form_text_cannot_govern(container):
    body = UPDATE_HTML.replace(RELATION, f'<{container}><option>{RELATION.decode()}</option></{container}>'.encode())
    assert (await outcome(body)).analysis.verdict.value == 'UNRESOLVED'


@pytest.mark.asyncio
@pytest.mark.parametrize('selector', ['main::before', 'main::after', '.notice::before'])
async def test_r4_03_generated_qualifier(selector):
    style = ('<style>' + selector + ' {content:"DRAFT - NOT YET APPROVED"}</style>').encode()
    body = style + UPDATE_HTML.replace(b'<main>', b'<main class="notice">')
    assert (await outcome(body)).analysis.verdict.value == 'UNRESOLVED'


@pytest.mark.asyncio
@pytest.mark.parametrize('body, verdict', [(UPDATE_HTML, 'SUPERSEDED'), (CANCEL_HTML, 'CANCELLED'),
    (b'<nav>Scope for other notices.</nav>' + UPDATE_HTML, 'SUPERSEDED'),
    (UPDATE_HTML.replace(b'</main>', b'<p>Contact the office if assistance is needed.</p></main>'), 'SUPERSEDED'),
    (UPDATE_HTML.replace(b'</main>', b'<blockquote>The cancellation has been stayed by the court.</blockquote></main>'), 'SUPERSEDED'),
    (b'<style>nav::before {content:"Menu"}</style><nav>Navigation</nav>' + UPDATE_HTML, 'SUPERSEDED')])
async def test_semantic_and_html_positive_controls(body, verdict):
    out = await outcome(body)
    assert out.analysis.verdict.value == verdict and out.analysis.coverage.value == 'ADEQUATE'
    assert len(out.sources) == 2 and all(s.source_sha256 and s.snapshot_id for s in out.sources)


@pytest.mark.asyncio
@pytest.mark.parametrize('as_of', ['2026-10-10T00:30:00+05:30', '2026-10-10T07:00:00+05:30'])
async def test_r5_01_date_only_boundary(as_of):
    body = UPDATE_HTML.replace(b'2026-09-17', b'2026-10-10')
    out = await outcome(body, req=request().model_copy(update={'as_of': datetime.fromisoformat(as_of)}))
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert 'DATE_ONLY_ISSUANCE_INTRADAY_UNRESOLVED' in out.warnings


@pytest.mark.asyncio
@pytest.mark.parametrize('as_of, verdict', [('2026-10-08T00:00:00+00:00','SUPPORTED_BY_EVIDENCE'),
                                         ('2026-10-12T00:00:00+00:00','SUPERSEDED')])
async def test_date_only_clear_day_controls(as_of, verdict):
    body = UPDATE_HTML.replace(b'2026-09-17', b'2026-10-10')
    assert (await outcome(body, req=request().model_copy(update={'as_of':datetime.fromisoformat(as_of)}))).analysis.verdict.value == verdict


@pytest.mark.asyncio
@pytest.mark.parametrize('issuer, verdict', [('Department Alpha','SUPERSEDED'),('Department Beta','UNRESOLVED')])
async def test_r7_01_document_issuer(issuer, verdict):
    original = ORIG_HTML.replace(b'<main>', b'<main><p>Issued by Department Alpha.</p>')
    body = UPDATE_HTML.replace(b'<main>', ('<main><p>Issued by ' + issuer + '.</p>').encode())
    engine, _, _ = workflow([ORIGINAL,UPDATE], {ORIGINAL:original,UPDATE:body})
    engine.registry = registry()
    out = await engine.check(request().model_copy(update={'issuer_name':'Department Alpha'}))
    print('ISSUER',issuer,out.analysis.verdict.value,out.analysis.coverage.value)
    assert out.analysis.verdict.value == verdict


def registry():
    return IssuerAuthorityRegistry((AuthorityAttestation(issuer_id='synthetic', exact_host='issuer.example',
        canonical_issuer_name='Department Alpha',publication_path_prefixes=('/notices',),
        verification_evidence_url='https://directory.example/alpha',verified_at=datetime.now(timezone.utc),
        verification_method='MANUAL_OFFICIAL_DIRECTORY'),))


@pytest.mark.asyncio
async def test_r8_02_preflight_before_paid_discovery():
    engine,search,transport = workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML})
    engine.registry=registry()
    out=await engine.check(request(url='https://issuer.example/community-uploads/a').model_copy(update={'issuer_name':'Department Alpha'}))
    print('PATH_PREFLIGHT',len(search.calls),len(transport.calls),out.warnings)
    assert out.analysis.verdict.value == 'UNRESOLVED'
    assert not search.calls and not transport.calls


@pytest.mark.asyncio
async def test_issuer_exclusive_path_without_repeated_label():
    engine,_,_=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML})
    engine.registry=registry()
    out=await engine.check(request(url=ORIGINAL).model_copy(update={'issuer_name':'Department Alpha'}))
    assert out.analysis.verdict.value=='SUPERSEDED'


@pytest.mark.asyncio
@pytest.mark.parametrize('reverse', [False,True])
async def test_r6_02_fragment_aliases(reverse):
    urls=[u+'#section-'+str(i) for u in (ORIGINAL,UPDATE) for i in range(7)]
    if reverse: urls.reverse()
    engine,search,transport=workflow(urls,{**{u:ORIG_HTML for u in urls if 'corrigendum' not in u},
                                         **{u:UPDATE_HTML for u in urls if 'corrigendum' in u}, ORIGINAL:ORIG_HTML, UPDATE:UPDATE_HTML})
    out=await engine.check(request())
    print('ALIASES',out.analysis.verdict.value,out.warnings,len(transport.calls))
    assert out.analysis.verdict.value=='SUPERSEDED' and len(transport.calls)==2
    assert len(search.calls)==6


@pytest.mark.parametrize('fragment',['access_token=SYNTHETIC_CANARY','%61uth=SYNTHETIC_CANARY','section&SESSION=SYNTHETIC_CANARY'])
def test_r7_02_fragments_rejected_and_sanitized(fragment):
    url=ORIGINAL+'#'+fragment
    with pytest.raises(SourceFailure): safe_target(url)
    assert 'SYNTHETIC_CANARY' not in str(sanitize_for_persistence({'url':url}))


@pytest.mark.asyncio
@pytest.mark.parametrize('capacity, expected',[(2,'UNRESOLVED'),(3,'SUPERSEDED')])
async def test_r5_03_preserve_all_capture_retention_policy(tmp_path,capacity,expected):
    unrelated='https://issuer.example/notices/meeting'
    engine,_,_=workflow([ORIGINAL,UPDATE,unrelated],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML,unrelated:b'<main>General institutional meeting notes without an operative notice.</main>'})
    engine.snapshot_store=SnapshotStore(tmp_path,max_snapshots=capacity)
    out=await engine.check(request())
    print('RETENTION',capacity,out.analysis.verdict.value,out.warnings,len(list(tmp_path.glob('*.json'))))
    assert out.analysis.verdict.value==expected
    assert len(list(tmp_path.glob('*.json')))==capacity


@pytest.mark.asyncio
@pytest.mark.parametrize('meta',['<meta http-equiv="refresh" content="0; url=/notices/new">',
    '<meta HTTP-EQUIV="REFRESH" content="30; URL=https://issuer.example/notices/new">',
    '<meta http-equiv="refresh" content="invalid">'])
async def test_r8_01_unexamined_navigation(meta):
    engine,_,transport=workflow([ORIGINAL],{ORIGINAL:meta.encode()+ORIG_HTML})
    out=await engine.check(request())
    assert out.analysis.verdict.value=='UNRESOLVED'
    assert transport.calls==[ORIGINAL]


@pytest.mark.parametrize('stamp',['0001-01-01T00:00:00+14:00','9999-12-31T23:59:59-14:00'])
def test_r7_03_extreme_timestamp_input(stamp):
    engine,search,_=workflow([ORIGINAL],{ORIGINAL:ORIG_HTML})
    with TestClient(create_app(engine),raise_server_exceptions=False) as client:
        payload=request().model_dump(mode='json');payload['as_of']=stamp
        response=client.post('/api/check',json=payload)
        print('TIMESTAMP',stamp,response.status_code)
    assert response.status_code==422 and not search.calls


def test_r4_05_global_demo_limit_is_intentional(monkeypatch):
    import app.api.main as main
    from app.application.demo import run_demo
    import asyncio
    result=asyncio.run(run_demo(request().supplied_deadline))
    async def synthetic(_): return result
    monkeypatch.setattr(main,'run_demo',synthetic)
    with TestClient(create_app(None)) as client:
        codes=[client.post('/api/demo/check',json={'supplied_deadline':'2026-10-01'}).status_code for _ in range(13)]
    print('DEMO_POLICY',codes)
    assert codes==[200]*12+[429]


@pytest.mark.parametrize('case',['cancellation','fee'])
def test_r6_01_precedence(family,helpers,case):
    from app.domain import analyze, CriticalField, DocumentRole, EventType, ResolutionContext, EvidenceCoverage
    d,a,e,b=(helpers[n] for n in ('make_doc','assertion','event','binding'))
    docs=[d('orig',DocumentRole.ORIGINAL_NOTICE,[a('orig',CriticalField.DEADLINE,'2026-10-01')]),
          d('ext',DocumentRole.EXTENSION,[a('ext',CriticalField.DEADLINE,'2026-10-26')],issued_day=10)]
    events=[e('original',family.family_id,'orig',EventType.DECLARES,[CriticalField.DEADLINE],1),
            e('update',family.family_id,'ext',EventType.EXTENDS,[CriticalField.DEADLINE],10,targets=('original',))]
    binds=[b('orig'),b('ext')]
    inputs={CriticalField.DEADLINE:'2026-10-01'}
    if case=='cancellation':
        docs.append(d('cancel',DocumentRole.CANCELLATION,issued_day=11))
        events.append(e('cancel-event',family.family_id,'cancel',EventType.CANCELS,day=11))
        binds.append(b('cancel'));expected='UNRESOLVED'
    else:
        docs[0]=d('orig',DocumentRole.ORIGINAL_NOTICE,[a('orig',CriticalField.DEADLINE,'2026-10-01'),
                   a('orig',CriticalField.FEE,'INR 50')])
        for identifier,day,value in [('fee',11,'INR 100'),('withdraw',12,'INR 200')]:
            docs.append(d(identifier,DocumentRole.CORRIGENDUM,[a(identifier,CriticalField.FEE,value)],issued_day=day))
            events.append(e(identifier,family.family_id,identifier,EventType.AMENDS,[CriticalField.FEE],day,targets=('original',)))
            binds.append(b(identifier))
        inputs[CriticalField.FEE]='INR 50';expected='CONFLICT'
    out=analyze(family,inputs,docs,events,binds,ResolutionContext(as_of=helpers['dt'](30)),EvidenceCoverage.ADEQUATE)
    print('PRECEDENCE',case,out.verdict.value,[r.status.value for r in out.field_resolutions])
    assert out.verdict.value==expected
    if case=='cancellation':
        assert all(r.value is None and r.status.value=='UNRESOLVED' for r in out.field_resolutions)
        assert all(r.reason=='UNRESOLVED_GOVERNING_STATUS' for r in out.field_resolutions)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind, verdict', [('visible','SUPERSEDED'),('overlay','UNRESOLVED'),('inline','UNRESOLVED')])
async def test_pdf_admission_through_complete_workflow(kind, verdict):
    import fitz
    with fitz.open() as pdf:
        page=pdf.new_page()
        for i,line in enumerate(['Corrigendum','Reference: A/2026','Issued: 2026-09-17',RELATION.decode()]):
            page.insert_text((20,40+i*20),line,fontsize=11)
        if kind=='overlay':
            rect=page.search_for('26 October 2026')[0]
            rect.x1=rect.x0+fitz.get_text_length('26',fontsize=11)
            page.draw_rect(rect,color=None,fill=(1,1,1))
        if kind=='inline':
            xref=pdf.get_new_xref();pdf.update_object(xref,'<<>>')
            streams=b'\n'.join(pdf.xref_stream(x) for x in page.get_contents())
            pdf.update_stream(xref,streams+b'\nq 80 0 0 30 20 540 cm BI /W 2 /H 1 /CS /RGB /BPC 8 ID '+bytes([0,0,0,255,255,255])+b' EI Q')
            page.set_contents(xref)
        body=pdf.tobytes()
    engine,search,transport=workflow([ORIGINAL,UPDATE],{ORIGINAL:ORIG_HTML,UPDATE:body})
    original_get=transport.get
    def get(url,limit):
        status,headers,data=original_get(url,limit)
        return status,{'content-type':'application/pdf' if url==UPDATE else 'text/html'},data
    transport.get=get
    out=await engine.check(request())
    assert out.analysis.verdict.value==verdict
    assert out.analysis.coverage.value==('ADEQUATE' if kind=='visible' else 'INSUFFICIENT')
    assert len(out.sources)==(2 if kind=='visible' else 1)
    assert len(search.calls)==6 and transport.calls==[ORIGINAL,UPDATE]
    assert all(s.source_sha256 and s.snapshot_id for s in out.sources)


@pytest.mark.asyncio
@pytest.mark.parametrize('truncated',[False,True])
async def test_http_framing_through_capture_workflow(monkeypatch,truncated):
    import io
    import app.sources.fetch as fetch
    from app.sources import SafeSourceFetcher, PinnedHTTPTransport
    messages=[]
    for data in (ORIG_HTML,UPDATE_HTML):
        declared=len(data)+(20 if truncated and data==UPDATE_HTML else 0)
        messages.append(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: '+str(declared).encode()+b'\r\n\r\n'+data)
    sockets=[]
    class Socket:
        def __init__(self): self.body=messages.pop(0);self.closed=False
        def makefile(self,*args): return io.BytesIO(self.body)
        def sendall(self,_): pass
        def settimeout(self,_): pass
        def close(self): self.closed=True
    def connect(*a,**kw):
        sock=Socket();sockets.append(sock);return sock
    class TLS:
        def wrap_socket(self,sock,**kw): return sock
    monkeypatch.setattr(fetch.socket,'create_connection',connect)
    monkeypatch.setattr(fetch.ssl,'create_default_context',TLS)
    engine,search,_=workflow([ORIGINAL,UPDATE],{})
    engine.fetcher=SafeSourceFetcher(PinnedHTTPTransport(resolve=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))]))
    out=await engine.check(request())
    assert out.analysis.verdict.value==('UNRESOLVED' if truncated else 'SUPERSEDED')
    assert len(out.sources)==(1 if truncated else 2)
    assert len(search.calls)==6 and len(sockets)==2 and all(sock.closed for sock in sockets)
    assert len(list(engine.snapshot_store.root.glob('*.json')))==(1 if truncated else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize('date_text,verdict',[('0001-01-01','UNRESOLVED'),('9999-12-31','SUPPORTED_BY_EVIDENCE')])
async def test_source_issue_date_range_boundary(date_text,verdict):
    out=await outcome(UPDATE_HTML.replace(b'2026-09-17',date_text.encode()))
    assert out.analysis.verdict.value==verdict
    if verdict=='UNRESOLVED':assert 'ISSUANCE_DATE_RANGE_UNSUPPORTED' in out.warnings
    else:assert str(out.analysis.field_resolutions[0].value)=='2026-10-01'


@pytest.mark.asyncio
@pytest.mark.parametrize('addition',[
    '<select><option>Choose language</option></select>',
    '<datalist><option>Office contact</option></datalist>',
    '<textarea>Feedback to the office</textarea>',
    '<meta name="description" content="Notice details">',
    '<blockquote><header>Applicable only to historical notices.</header></blockquote>',
])
async def test_irrelevant_html_context_positive_controls(addition):
    assert (await outcome(addition.encode()+UPDATE_HTML)).analysis.verdict.value=='SUPERSEDED'


@pytest.mark.asyncio
async def test_unsupported_generated_selector_fails_closed():
    body=b'<style>main:unknown::before {content:"DRAFT"}</style>'+UPDATE_HTML
    assert (await outcome(body)).analysis.verdict.value=='UNRESOLVED'


@pytest.mark.asyncio
@pytest.mark.parametrize('host,verdict,captures',[('other.example','SUPERSEDED',2),('issuer.example','UNRESOLVED',0)])
async def test_url_fetch_policy_does_not_promote_unrelated_search_noise(host,verdict,captures):
    unusual='https://'+host+':8443/general-news'
    engine,search,transport=workflow([ORIGINAL,UPDATE,unusual],{ORIGINAL:ORIG_HTML,UPDATE:UPDATE_HTML})
    out=await engine.check(request())
    assert out.analysis.verdict.value==verdict and len(transport.calls)==captures
    assert len(search.calls)==6
