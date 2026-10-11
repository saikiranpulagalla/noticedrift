"""Immutable source evidence: only bytes from a pinned connection enter the parser."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from hashlib import sha256
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from app.url_credentials import has_url_credentials

class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')

class SourceErrorCode(str, Enum):
    UNSAFE_URL = 'UNSAFE_URL'
    DNS_UNSAFE = 'DNS_UNSAFE'
    NETWORK_ERROR = 'NETWORK_ERROR'
    REDIRECT_LIMIT = 'REDIRECT_LIMIT'
    HTTP_ERROR = 'HTTP_ERROR'
    OVERSIZED = 'OVERSIZED'
    UNSUPPORTED_MEDIA = 'UNSUPPORTED_MEDIA'
    PARSE_FAILED = 'PARSE_FAILED'
    UNSUPPORTED_STRUCTURE = 'UNSUPPORTED_STRUCTURE'
    SOURCE_INTEGRITY_ERROR = 'SOURCE_INTEGRITY_ERROR'
    STORAGE_ERROR = 'STORAGE_ERROR'
    UNVERIFIED_AUTHORITY = 'UNVERIFIED_AUTHORITY'
    UNGROUNDED_ASSERTION = 'UNGROUNDED_ASSERTION'

class SourceFailure(Exception):
    def __init__(self, code: SourceErrorCode):
        self.code = code
        super().__init__(code.value)  # Never propagate arbitrary remote diagnostic text.

class SourceSnapshot(FrozenModel):
    source_url: str
    final_url: str
    captured_at: datetime
    content_type: str
    body: bytes
    body_sha256: str
    redirect_chain: tuple[str, ...] = ()
    status_code: int = 200

    @field_validator('source_url', 'final_url')
    @classmethod
    def credential_free_url(cls, value: str) -> str:
        if has_url_credentials(value):
            raise ValueError('CREDENTIAL_BEARING_SOURCE_URL')
        return value

    @field_validator('redirect_chain')
    @classmethod
    def credential_free_redirects(cls, values):
        if any(has_url_credentials(value) for value in values):
            raise ValueError('CREDENTIAL_BEARING_SOURCE_URL')
        return values

    @field_validator('captured_at')
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError('CAPTURE_TIME_MUST_BE_AWARE')
        return value

    @model_validator(mode='after')
    def check_digest(self):
        if sha256(self.body).hexdigest() != self.body_sha256:
            raise ValueError('SOURCE_DIGEST_MISMATCH')
        return self

class ParsedSource(FrozenModel):
    snapshot_sha256: str
    normalized_text_sha256: str
    text: str
    status: str  # PARSED | PARTIAL | UNSUPPORTED | FAILED
    warning_codes: tuple[str, ...] = ()
    # PDF page start/end offsets (0-based start, exclusive end) in final normalized text.
    pages: tuple[tuple[int, int, int], ...] = ()

    @model_validator(mode='after')
    def check_digest(self):
        if sha256(self.text.encode('utf-8')).hexdigest() != self.normalized_text_sha256:
            raise ValueError('TEXT_DIGEST_MISMATCH')
        if any(start < 0 or end > len(self.text) or start > end for _,start,end in self.pages):
            raise ValueError('INVALID_PAGE_OFFSETS')
        return self

class EvidenceSpan(FrozenModel):
    snapshot_sha256: str
    text_sha256: str
    start: int
    end: int
    quotation: str
    page_number: int | None = None

class AuthorityAttestation(FrozenModel):
    issuer_id: str
    exact_host: str
    verification_evidence_url: str
    verified_at: datetime
    verification_method: str
    # Optional operator-corroborated canonical issuer label. User-supplied issuer
    # names must not override this identity or be displayed as verified.
    canonical_issuer_name: str | None = None
    # Optional independently-reviewed publication path allowlist. Empty means
    # only host and explicit user-content denylists have been checked.
    publication_path_prefixes: tuple[str, ...] = ()
    # Attestations are curated by the application operator, NEVER inferred from retrieved pages.
    @field_validator('canonical_issuer_name')
    @classmethod
    def canonical_name(cls, v):
        if v is not None and (not v.strip() or len(v) > 200):
            raise ValueError('INVALID_CANONICAL_ISSUER_NAME')
        return v

    @field_validator('publication_path_prefixes')
    @classmethod
    def safe_publication_prefixes(cls, prefixes):
        if len(prefixes) > 12:
            raise ValueError('TOO_MANY_PUBLICATION_PATH_PREFIXES')
        for prefix in prefixes:
            if (not prefix.startswith('/') or len(prefix) > 180 or
                    any(c in prefix for c in ['\\', '%', '?', '#', '\x00']) or
                    any(part in {'.', '..'} for part in prefix.split('/'))):
                raise ValueError('UNSAFE_PUBLICATION_PATH_PREFIX')
        return prefixes

    @field_validator('verified_at')
    @classmethod
    def valid_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError('ATTESTATION_TIME_MUST_BE_AWARE')
        return value
