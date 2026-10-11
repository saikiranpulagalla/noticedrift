"""Shared credential-name guard; never inspect or log credential values."""
import re
from urllib.parse import parse_qsl, urlsplit


def credential_query_key(key: str) -> bool:
    normalized = re.sub(r'[^a-z0-9]', '', key.casefold())
    return normalized in {
        'apikey', 'xapikey', 'key', 'auth', 'authorization', 'credential',
        'credentials', 'session', 'sessionid', 'cookie', 'signature', 'sig',
        'awsaccesskeyid', 'accesskey', 'accesskeyid', 'xamzcredential',
        'xamzsignature', 'xgoogcredential', 'xgoogsignature',
    } or normalized.endswith(('token', 'secret', 'password'))


def has_url_credentials(url: str) -> bool:
    return any(credential_query_key(key) for key, _ in
               parse_qsl(urlsplit(url).query, keep_blank_values=True))
