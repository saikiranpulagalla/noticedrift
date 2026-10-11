"""SSRF-resistant, pinned-IP, HTTP/1.1 one-shot GET transport.

Security invariants: resolve every redirect; connect to *validated numeric IP*, never
ask the HTTP stack to resolve again; TLS validates certificate against original hostname.
No ambient proxy, cookies, credentials, compressed response, or arbitrary ports.
"""
from __future__ import annotations
import http.client
import ipaddress
import socket
import ssl
import re
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urljoin, urlsplit, quote, parse_qsl
from .models import SourceFailure, SourceErrorCode, SourceSnapshot
from app.url_credentials import has_url_credentials

_MAX_BYTES = 8_000_000
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MEDIA = {'text/html','application/pdf','text/plain'}


def safe_target(url: str) -> tuple[str, str, int, str]:
    """Return (scheme, ASCII host, port, resource path). Never accept userinfo."""
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise SourceFailure(SourceErrorCode.UNSAFE_URL)
    try:
        u = urlsplit(url)
        if u.scheme not in ('https','http') or not u.netloc or u.username is not None or u.password is not None:
            raise ValueError()
        if not u.hostname or '%' in u.netloc or '\\' in url:
            raise ValueError()
        host = u.hostname.rstrip('.').encode('idna').decode('ascii').lower()
        # Ban ambiguous numeric spellings, including shortened/octal/hex host forms.
        if not host or len(host) > 253 or any(len(label) > 63 for label in host.split('.')):
            raise ValueError()
        if not re.fullmatch(r'[a-z0-9.:-]+', host):
            raise ValueError()
        if re.fullmatch(r'\d+', host) or re.fullmatch(r'0x[0-9a-f]+', host):
            raise ValueError()
        if host in {'localhost','localhost.localdomain'} or host.endswith('.localhost'):
            raise ValueError()
        try:
            literal_ip = ipaddress.ip_address(host)
        except ValueError:
            literal_ip = None
        if literal_ip is not None and not literal_ip.is_global:
            raise ValueError()
        # DNS-public resolution is checked again at the actual socket-connection boundary.

        if any(label.startswith('0x') for label in host.split('.')):
            raise ValueError()
        if len(host.split('.')) == 4 and any(re.fullmatch(r'0\d+', label) for label in host.split('.')):
            raise ValueError()
        port = u.port or (443 if u.scheme == 'https' else 80)
        if port != (443 if u.scheme == 'https' else 80):
            raise ValueError()
        # Do not persist or transmit URLs carrying credential-like query fields.
        if has_url_credentials(url):
            raise ValueError()
        path = (u.path or '/') + (('?' + u.query) if u.query else '')
        if len(path) > 4096:
            raise ValueError()
        return u.scheme, host, port, path
    except (ValueError, OverflowError, UnicodeError):
        raise SourceFailure(SourceErrorCode.UNSAFE_URL) from None


def public_addresses(host: str, port: int, *, resolve=socket.getaddrinfo) -> tuple[str, ...]:
    try:
        infos = resolve(host, port, type=socket.SOCK_STREAM)
        addresses = tuple(dict.fromkeys(info[4][0] for info in infos))
        if not addresses:
            raise ValueError()
        # Fail closed if ANY DNS answer is non-global; do not select a 'safe' member from a mixed set.
        if any(not ipaddress.ip_address(addr).is_global for addr in addresses):
            raise SourceFailure(SourceErrorCode.DNS_UNSAFE)
        return addresses
    except SourceFailure:
        raise
    except (OSError, ValueError, TypeError):
        raise SourceFailure(SourceErrorCode.DNS_UNSAFE) from None


class PinnedHTTPTransport:
    """Connection injection is intentionally narrow: fake transports can test fetch policy offline."""
    def __init__(self, *, resolve=socket.getaddrinfo, timeout=7.0):
        self.resolve = resolve
        self.timeout = timeout

    def get(self, url: str, max_bytes: int) -> tuple[int, dict[str, str], bytes]:
        scheme, host, port, path = safe_target(url)
        addresses = public_addresses(host, port, resolve=self.resolve)
        last_error = None
        for ip in addresses[:2]:  # Keep address fallback bounded under a deadline.
            sock = None
            try:
                sock = socket.create_connection((ip, port), timeout=self.timeout)
                sock.settimeout(self.timeout)
                if scheme == 'https':
                    sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
                host_header = ('[' + host + ']') if ':' in host else host
                encoded_path = quote(path, safe='/%?&=:@+$,;~*-._!')
                request = (f'GET {encoded_path} HTTP/1.1\r\nHost: {host_header}\r\n'
                           'User-Agent: NoticeDrift/0.6 (+offline-evidence-checker)\r\n'
                           'Accept: text/html,application/pdf,text/plain\r\n'
                           'Accept-Encoding: identity\r\nConnection: close\r\n\r\n')
                sock.sendall(request.encode('ascii'))
                response = http.client.HTTPResponse(sock)
                response.begin()
                headers = {key.lower(): value for key,value in response.getheaders()}
                if response.status not in _REDIRECT_CODES:
                    try:
                        content_length = int(headers.get('content-length', '-1'))
                        if content_length > max_bytes:
                            raise SourceFailure(SourceErrorCode.OVERSIZED)
                    except ValueError:
                        pass
                body = b'' if response.status in _REDIRECT_CODES else response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise SourceFailure(SourceErrorCode.OVERSIZED)
                return response.status, headers, body
            except SourceFailure:
                raise
            except (OSError, ssl.SSLError, http.client.HTTPException, UnicodeError) as exc:
                last_error = exc
            finally:
                if sock is not None:
                    sock.close()
        raise SourceFailure(SourceErrorCode.NETWORK_ERROR) from last_error


class SafeSourceFetcher:
    def __init__(self, transport=None, *, max_bytes: int = _MAX_BYTES, max_redirects: int = 3):
        if not isinstance(max_bytes, int) or not 1 <= max_bytes <= _MAX_BYTES:
            raise ValueError('INVALID_FETCH_SIZE')
        if not isinstance(max_redirects, int) or not 0 <= max_redirects <= 3:
            raise ValueError('INVALID_REDIRECT_LIMIT')
        self.transport = transport or PinnedHTTPTransport()
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects

    def fetch(self, url: str, *, allowed_hosts: frozenset[str] | None = None) -> SourceSnapshot:
        safe_target(url)
        seen: set[str] = set()
        chain: list[str] = []
        current = url
        for step in range(self.max_redirects + 1):
            _, host, _, _ = safe_target(current)
            if allowed_hosts is not None and host not in allowed_hosts:
                raise SourceFailure(SourceErrorCode.UNVERIFIED_AUTHORITY)
            if current in seen:
                raise SourceFailure(SourceErrorCode.REDIRECT_LIMIT)
            seen.add(current)
            status, headers, body = self.transport.get(current, self.max_bytes)
            if len(body) > self.max_bytes:
                raise SourceFailure(SourceErrorCode.OVERSIZED)
            if status in _REDIRECT_CODES:
                if step == self.max_redirects:
                    raise SourceFailure(SourceErrorCode.REDIRECT_LIMIT)
                location = headers.get('location')
                if not location:
                    raise SourceFailure(SourceErrorCode.HTTP_ERROR)
                next_url = urljoin(current, location)
                safe_target(next_url)
                if urlsplit(current).scheme == 'https' and urlsplit(next_url).scheme == 'http':
                    raise SourceFailure(SourceErrorCode.UNSAFE_URL)
                chain.append(current)
                current = next_url
                continue
            if status != 200:
                raise SourceFailure(SourceErrorCode.HTTP_ERROR)
            if headers.get('content-encoding', 'identity').strip().lower() != 'identity':
                raise SourceFailure(SourceErrorCode.UNSUPPORTED_MEDIA)
            media = headers.get('content-type', '').split(';',1)[0].strip().lower()
            # Media cannot be trusted solely from extension or Content-Type.
            if media not in _MEDIA:
                raise SourceFailure(SourceErrorCode.UNSUPPORTED_MEDIA)
            if media == 'application/pdf' and not body.startswith(b'%PDF-'):
                raise SourceFailure(SourceErrorCode.UNSUPPORTED_MEDIA)
            if media in {'text/html','text/plain'} and body.startswith(b'%PDF-'):
                raise SourceFailure(SourceErrorCode.UNSUPPORTED_MEDIA)
            return SourceSnapshot(source_url=url, final_url=current,
                                  content_type=media, body=body,
                                  body_sha256=sha256(body).hexdigest(),
                                  redirect_chain=tuple(chain), status_code=200,
                                  captured_at=datetime.now(timezone.utc))
        raise SourceFailure(SourceErrorCode.REDIRECT_LIMIT)
