import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"gclid", "fbclid"}

def canonical_scope_value(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = "".join(c for c in value if unicodedata.category(c) != "Cf")
    return " ".join(value.casefold().split())


def normalize_reference(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = "".join(c for c in value if unicodedata.category(c) != "Cf")
    value = value.strip().upper().replace("–", "-").replace("—", "-").replace("‑", "-").replace("−", "-")
    value = re.sub(r"\s*([/\-])\s*", r"\1", value)
    value = re.sub(r"\s+", " ", value)
    return value

def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        kl = k.lower()
        if kl in _TRACKING_KEYS or any(kl.startswith(p) for p in _TRACKING_PREFIXES):
            continue
        query.append((k, v))
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("UNSAFE_SOURCE_URL")
    if parts.port not in (None, 80, 443):
        raise ValueError("UNSUPPORTED_URL_PORT")
    hostname = parts.hostname.encode("idna").decode("ascii").lower()
    # Fragment routes can select a DIFFERENT application form in SPA portals.
    # Ordinary document anchors are presentation hints and remain ignored.
    fragment = parts.fragment if parts.fragment.startswith(("/", "!")) else ""
    return urlunsplit((parts.scheme.lower(), hostname, parts.path or "/", urlencode(query, doseq=True), fragment))
