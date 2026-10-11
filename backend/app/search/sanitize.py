"""Persistence boundary: values from providers are data, never trusted log strings."""
from __future__ import annotations
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from pydantic import BaseModel
from app.url_credentials import credential_query_key

SENSITIVE_KEYS = {"api_key", "apikey", "api-key", "x-api-key", "access_token", "id_token", "auth",
                  "authorization", "token", "secret", "password", "cookie", "key", "credential",
                  "signature", "sig", "session", "session_id", "client_secret", "error"}

def _sensitive(key):
    k = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return k in {re.sub(r"[^a-z0-9]", "", s) for s in SENSITIVE_KEYS} or credential_query_key(str(key))

def sanitize_url(url: str) -> str:
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    netloc = hostname + ((":" + str(parts.port)) if parts.port else "")
    q = [(k, "<redacted>" if _sensitive(k) else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(q), parts.fragment))

def sanitize_for_persistence(value: Any) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: "<redacted>" if _sensitive(k) else sanitize_for_persistence(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [sanitize_for_persistence(v) for v in value]
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return sanitize_url(value)
        value = re.sub(r"https?://[^\s<>\"']+", lambda m: sanitize_url(m.group(0)), value)
        if re.search(r"(?i)\b(?:bearer|basic)\s+\S+", value):
            return re.sub(r"(?i)\b(?:bearer|basic)\s+\S+", "<redacted-auth>", value)
    return value
