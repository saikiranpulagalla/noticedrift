"""Bounded synthetic transport and PDF fixtures; no network destinations."""
import io
import time
from datetime import datetime,timezone
from hashlib import sha256
import pytest
import fitz
from app.sources import PinnedHTTPTransport, SafeSourceFetcher, SourceFailure, parse_snapshot
from app.sources.models import SourceSnapshot


class MemorySocket:
    def __init__(self,message): self.message=message;self.closed=False
    def makefile(self,*args): return io.BytesIO(self.message)
    def sendall(self,_): pass
    def settimeout(self,_): pass
    def close(self): self.closed=True


def transport(monkeypatch,message,timeout=1):
    import app.sources.fetch as fetch
    sock=MemorySocket(message)
    monkeypatch.setattr(fetch.socket,'create_connection',lambda *a,**k:sock)
    return PinnedHTTPTransport(resolve=lambda *a,**k:[(None,None,None,None,('8.8.8.8',80))],timeout=timeout),sock


@pytest.mark.parametrize('headers,body,valid',[
    (b'Content-Length: 3',b'yes',True),
    (b'Content-Length: 4',b'yes',False),
    (b'Content-Length: rubbish',b'yes',False),
    (b'Content-Length: -1',b'yes',False),
    (b'Content-Length: 3\r\nContent-Length: 4',b'yes',False),
    (b'Transfer-Encoding: chunked',b'3\r\nyes\r\n0\r\n\r\n',True),
    (b'Transfer-Encoding: chunked',b'3\r\nye',False),
    (b'Transfer-Encoding: chunked\r\nContent-Length: 3',b'3\r\nyes\r\n0\r\n\r\n',False),
    (b'',b'yes',True),
    (b'Content-Length: 0',b'',True),
])
def test_invisible_01_framing(monkeypatch,headers,body,valid):
    runner,sock=transport(monkeypatch,b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n'+(headers+b'\r\n' if headers else b'')+b'\r\n'+body)
    if valid:
        _,_,captured=runner.get('http://issuer.example/a',100)
        assert captured in (b'yes',b'')
    else:
        with pytest.raises(SourceFailure): runner.get('http://issuer.example/a',100)
    assert sock.closed


def test_r4_04_transfer_budget(monkeypatch):
    import app.sources.fetch as fetch
    class Trickle(io.BytesIO):
        def read(self,n=-1): time.sleep(.01);return super().read(n)
        def read1(self,n=-1): time.sleep(.01);return super().read(min(n,1))
        def readline(self,n=-1): time.sleep(.04);return super().readline(n)
    message=b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 3\r\n\r\nyes'
    runner,sock=transport(monkeypatch,message,timeout=.025)
    sock.makefile=lambda *a:Trickle(message)
    start=time.monotonic()
    with pytest.raises(SourceFailure):runner.get('http://issuer.example/a',100)
    assert sock.closed
    print('TRANSFER_ELAPSED',time.monotonic()-start)


def test_r8_03_blocking_dns_residual_is_explicit():
    def slow(*a,**k):time.sleep(.06);raise OSError('synthetic DNS failure')
    start=time.monotonic()
    with pytest.raises(SourceFailure):PinnedHTTPTransport(resolve=slow,timeout=.005).get('http://issuer.example/a',100)
    print('DNS_BLOCKING_ELAPSED',time.monotonic()-start)
    # No timeout-thread workaround: synchronous OS resolution is drained.
    assert time.monotonic()-start>.005  # Exceeds the configured budget, independent of Windows clock granularity.


def pdf_bytes(*,overlay=False,inline=False,count=1,decorations=0,opacity=1,background=False):
    with fitz.open() as doc:
        page=doc.new_page(width=720,height=720)
        if background:page.draw_rect(fitz.Rect(15,15,705,705),color=None,fill=(1,1,1))
        lines=['Corrigendum','Reference: A/2026','Issued: 2026-09-17',
               'The deadline is extended from 01 October 2026 to 26 October 2026.']
        for i,line in enumerate(lines):page.insert_text((20,40+i*20),line,fontsize=11)
        if overlay:
            rect=page.search_for('26 October 2026')[0]
            rect.x1=rect.x0+fitz.get_text_length('26',fontsize=11)
            page.draw_rect(rect,color=None,fill=(1,1,1),fill_opacity=opacity)
        if inline:
            # Inline image syntax, deliberately not an image XObject.
            xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
            doc.update_stream(xref,b'q 80 0 0 30 20 540 cm BI /W 2 /H 1 /CS /RGB /BPC 8 ID '+bytes([0,0,0,255,255,255])+b' EI Q')
            existing=page.get_contents()
            page.set_contents(xref)
            streams=b'\n'.join(doc.xref_stream(x) for x in existing)+b'\n'+doc.xref_stream(xref)
            doc.update_stream(xref,streams)
        for i in range(count-1):page.insert_text((20,150+i%500),f'Administrative line {i}',fontsize=5)
        for i in range(decorations):page.draw_rect(fitz.Rect(680,20+i%600,685,22+i%600),color=None,fill=(0,0,0))
        return doc.tobytes()


def snapshot(body):
    return SourceSnapshot(source_url='https://issuer.example/notices/a',final_url='https://issuer.example/notices/a',
        captured_at=datetime.now(timezone.utc),body=body,body_sha256=sha256(body).hexdigest(),content_type='application/pdf')


@pytest.mark.parametrize('kind',['overlay','inline'])
def test_pdf_unsupported_visual_material(kind):
    body=pdf_bytes(**{kind:True})
    with fitz.open(stream=body,filetype='pdf') as doc:
        page=doc[0]
        print('PDF_STRUCTURE',kind,len(page.get_images(full=True)),len(page.get_image_info()))
        assert '26 October 2026' in page.get_text()
    parsed=parse_snapshot(snapshot(body))
    print('PDF_PARSE',kind,parsed.status,parsed.warning_codes)
    assert parsed.status!='PARSED'


@pytest.mark.parametrize('kwargs',[{}, {'decorations':50},{'overlay':True,'opacity':0}, {'background':True}])
def test_visible_pdf_controls(kwargs):
    parsed=parse_snapshot(snapshot(pdf_bytes(**kwargs)))
    assert parsed.status=='PARSED',parsed.warning_codes


def test_r6_03_pdf_work_scaling():
    durations=[]
    for count in (100,300):
        body=pdf_bytes(count=count,decorations=count)
        start=time.monotonic();parsed=parse_snapshot(snapshot(body));duration=time.monotonic()-start
        durations.append(duration)
        print('PDF_WORK',count,len(body),duration,parsed.status,parsed.warning_codes)
    assert max(durations)<10  # Generous smoke bound, not a performance certification.


def test_pdf_visual_fixture_render(tmp_path):
    for name,kwargs in [('visible',{}),('covered',{'overlay':True})]:
        body=pdf_bytes(**kwargs)
        (tmp_path/(name+'.pdf')).write_bytes(body)
        with fitz.open(stream=body,filetype='pdf') as doc:doc[0].get_pixmap(matrix=fitz.Matrix(2,2)).save(str(tmp_path/(name+'.png')))
    assert (tmp_path/'covered.png').is_file()


@pytest.mark.parametrize('timeout',[0,-1,float('inf'),float('nan'),'7'])
def test_transport_rejects_invalid_deadline(timeout):
    with pytest.raises(ValueError): PinnedHTTPTransport(timeout=timeout)


@pytest.mark.parametrize('message,limit',[
    (b'HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\nyes',100),
    (b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n',100),
    (b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Length: 3\r\n\r\nyes',100),
    (b'HTTP/1.1 200 OK\r\n\r\nyes',2),
])
def test_transport_unsupported_framing_and_unbounded_body(monkeypatch,message,limit):
    runner,sock=transport(monkeypatch,message)
    with pytest.raises(SourceFailure):runner.get('http://issuer.example/a',limit)
    assert sock.closed


def test_source_deadline_includes_address_fallback(monkeypatch):
    import app.sources.fetch as fetch
    sock=MemorySocket(b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nyes')
    calls=[]
    def connect(*a,**kw):
        calls.append(kw['timeout'])
        if len(calls)==1:raise OSError('synthetic first address failure')
        return sock
    monkeypatch.setattr(fetch.socket,'create_connection',connect)
    runner=PinnedHTTPTransport(resolve=lambda *a,**k:[(None,None,None,None,(ip,80)) for ip in ('8.8.8.8','1.1.1.1')])
    assert runner.get('http://issuer.example/a',10)[2]==b'yes'
    assert len(calls)==2 and calls[1]<=calls[0] and sock.closed


def test_source_dns_return_after_budget_never_dispatches(monkeypatch):
    import app.sources.fetch as fetch
    def resolve(*a,**k):
        time.sleep(.015)
        return [(None,None,None,None,('8.8.8.8',80))]
    def forbidden(*a,**k):raise AssertionError('expired DNS budget dispatched a connection')
    monkeypatch.setattr(fetch.socket,'create_connection',forbidden)
    with pytest.raises(SourceFailure):PinnedHTTPTransport(resolve=resolve,timeout=.001).get('http://issuer.example/a',10)


def test_deadline_file_read_and_header_limits():
    from app.sources.fetch import _DeadlineFile
    sock=MemorySocket(b'')
    raw=io.BytesIO(b'a'*40_000+b'\n'+b'b'*40_000+b'\n')
    reader=_DeadlineFile(raw,sock,time.monotonic()+5)
    with pytest.raises(ValueError):reader.read()
    assert reader.readline(0)==b''
    assert reader.readline().endswith(b'\n')
    with pytest.raises(SourceFailure):reader.readline()
    reader.flush();reader.close();reader.flush()


class GeometryPage:
    def __init__(self,sequence=(),traces=(),drawings=()):
        self.sequence,self.traces,self.drawings=sequence,traces,drawings
    def get_bboxlog(self):return self.sequence
    def get_texttrace(self):return self.traces
    def get_drawings(self):return self.drawings


@pytest.mark.parametrize('case',['operations','glyphs','geometry','entries','comparisons'])
def test_pdf_inspection_resource_limits(case):
    from app.sources.parse import _pdf_visibility
    glyph=(65,1,(1,1),(1,1,2,2))
    if case=='operations':page=GeometryPage(sequence=[('fill-text',(1,1,2,2))]*20_001)
    elif case=='glyphs':page=GeometryPage(traces=[{'chars':[glyph]*50_001}])
    elif case=='geometry':
        with pytest.raises(ValueError):_pdf_visibility(GeometryPage(sequence=[('fill-path',(0,0,1e6,1e6))]))
        return
    elif case=='entries':page=GeometryPage(sequence=[('fill-path',(0,0,6400,6400))]*10)
    else:page=GeometryPage(sequence=[('fill-path',(0,0,3,3))]*101,
                           traces=[{'chars':[glyph]*1000,'seqno':200,'size':11}])
    assert 'PDF_VISIBILITY_WORK_LIMIT' in _pdf_visibility(page)


def test_pdf_geometry_empty_and_invisible_text():
    from app.sources.parse import _pdf_visibility
    page=GeometryPage(sequence=[('ignore-text',(0,0,0,0)),('fill-path',(0,0,0,0))],
        traces=[{'chars':[],'type':3,'opacity':0,'size':1,'color':(1,1,1)}])
    warnings=_pdf_visibility(page)
    assert set(warnings)=={'PDF_NONVISIBLE_TEXT','PDF_TEXT_TOO_SMALL','PDF_LOW_CONTRAST_UNVERIFIED'}


def test_pdf_annotation_requires_review():
    with fitz.open(stream=pdf_bytes(),filetype='pdf') as doc:
        doc[0].add_text_annot((50,150),'Conditional application scope')
        body=doc.tobytes()
    parsed=parse_snapshot(snapshot(body))
    assert parsed.status!='PARSED' and 'PDF_ANNOTATIONS_UNVERIFIED' in parsed.warning_codes
