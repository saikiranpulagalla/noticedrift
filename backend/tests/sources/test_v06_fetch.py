from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import socket
import pytest
from app.sources import (SafeSourceFetcher, PinnedHTTPTransport, SourceFailure,
                         SourceErrorCode, safe_target, public_addresses)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def get(self, url, max_bytes):
        self.calls.append(url)
        return self.responses.pop(0)


def test_content_snapshot_integrity():
    response = (200, {'content-type':'text/html'}, b'<main>Official deadline 26 October 2026</main>')
    s = SafeSourceFetcher(FakeTransport([response])).fetch('https://issuer.example/notice')
    assert s.body_sha256 == sha256(response[2]).hexdigest()
    assert s.final_url == 'https://issuer.example/notice'
    with pytest.raises(ValueError):
        s.model_copy(update={'body': b'tampered'}).model_validate(s.model_copy(update={'body': b'tampered'}).model_dump())


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'ftp://google.com/', 'https://user:pw@example.com/',
    'http://localhost/a', 'https://a.localhost/a', 'http://127.0.0.1/a',
    'http://2130706433/a', 'http://0x7f000001/a', 'http://0177.0.0.1/a',
    'http://example.com:8080/x', 'https://example.com:8443/x',
    'http://evil\\@example.com', 'https://example.com/%0a\n',
    'https://x.test/%00\x00', 'http://a@b.example/',
])
def test_bad_urls_rejected(url):
    with pytest.raises(SourceFailure) as e:
        safe_target(url)
    assert e.value.code == SourceErrorCode.UNSAFE_URL


def test_hostname_validation_and_idna():
    assert safe_target('https://EXAMPLE.com/a?x=1')[1:] == ('example.com',443,'/a?x=1')
    assert safe_target('https://bücher.example/')[1] == 'xn--bcher-kva.example'


def fake_resolver(host, port, type):
    return [(None,None,None,None,('8.8.8.8', port))]


def test_dns_all_global_only():
    assert public_addresses('issuer.example',443,resolve=fake_resolver) == ('8.8.8.8',)
    for addresses in [('8.8.8.8', '127.0.0.1'), ('169.254.169.254',), ('::1',), ('10.0.0.1',)]:
        def resolver(host,port,type):
            return [(None,None,None,None,(x,port)) for x in addresses]
        with pytest.raises(SourceFailure) as exc:
            public_addresses('issuer.example',443,resolve=resolver)
        assert exc.value.code == SourceErrorCode.DNS_UNSAFE


def test_redirect_revalidated_and_cannot_bypass_url_safety():
    transport = FakeTransport([(302, {'location': 'http://127.0.0.1/metadata'}, b'')])
    with pytest.raises(SourceFailure) as err:
        SafeSourceFetcher(transport).fetch('https://issuer.example/notice')
    assert err.value.code == SourceErrorCode.UNSAFE_URL or err.value.code == SourceErrorCode.DNS_UNSAFE
    # Strict URL syntax itself allows a public-looking IP; pinned DNS/connect layer blocks it.
    assert transport.calls == ['https://issuer.example/notice']


def test_redirect_loop_and_limit():
    transport = FakeTransport([(301,{'location':'/a'},b''), (301,{'location':'/a'},b'')])
    with pytest.raises(SourceFailure) as err:
        SafeSourceFetcher(transport).fetch('https://issuer.example/start')
    assert err.value.code == SourceErrorCode.REDIRECT_LIMIT
    transport = FakeTransport([(302, {'location':'/1'},b''), (302,{'location':'/2'},b''),
                               (302,{'location':'/3'},b''), (302, {'location':'/4'},b'')])
    with pytest.raises(SourceFailure) as err:
        SafeSourceFetcher(transport, max_redirects=3).fetch('https://issuer.example/')
    assert err.value.code == SourceErrorCode.REDIRECT_LIMIT


def test_relative_redirect_and_header_policies():
    transport = FakeTransport([(302,{'location':'/new'},b''),
                               (200,{'content-type':'text/plain; charset=utf-8'},b'Notice updated')])
    snap = SafeSourceFetcher(transport).fetch('https://issuer.example/old')
    assert snap.final_url == 'https://issuer.example/new'
    assert snap.redirect_chain == ('https://issuer.example/old',)


@pytest.mark.parametrize('response,reason', [
    ((404, {'content-type':'text/html'},b''), SourceErrorCode.HTTP_ERROR),
    ((200, {'content-type':'application/zip'},b'x'), SourceErrorCode.UNSUPPORTED_MEDIA),
    ((200, {'content-type':'application/pdf'},b'fake'), SourceErrorCode.UNSUPPORTED_MEDIA),
    ((200, {'content-type':'text/html', 'content-encoding':'gzip'},b'abc'), SourceErrorCode.UNSUPPORTED_MEDIA),
    ((200, {'content-type':'text/html'},b'a'*12), SourceErrorCode.OVERSIZED),
])
def test_http_and_content_bounds(response,reason):
    with pytest.raises(SourceFailure) as exc:
        SafeSourceFetcher(FakeTransport([response]),max_bytes=10).fetch('https://issuer.example/a')
    assert exc.value.code == reason


def test_pinned_transport_connects_to_resolved_ip_not_hostname(monkeypatch):
    calls=[]
    peers=[]
    def connect(address,timeout):
        calls.append(address)
        client, server = socket.socketpair()
        server.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 3\r\nConnection: close\r\n\r\nyes')
        peers.append(server)
        return client
    monkeypatch.setattr(socket,'create_connection',connect)
    transport = PinnedHTTPTransport(resolve=fake_resolver)
    try:
        status,headers,body = transport.get('http://issuer.example/notices',100)
        assert body == b'yes' and status == 200 and calls == [('8.8.8.8',80)]
    finally:
        for peer in peers: peer.close()
