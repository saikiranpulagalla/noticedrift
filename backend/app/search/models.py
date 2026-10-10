from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from urllib.parse import urlsplit
import ipaddress

class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

class QueryPurpose(str, Enum):
    IDENTITY = "IDENTITY"
    OFFICIAL_SOURCE = "OFFICIAL_SOURCE"
    AMENDMENT = "AMENDMENT"
    EXTENSION = "EXTENSION"
    REVISION = "REVISION"
    CANCELLATION = "CANCELLATION"

class QueryTier(str, Enum):
    CORE = "CORE"
    EXPANSION = "EXPANSION"
    EMERGENCY = "EMERGENCY"

class SearchMode(str, Enum):
    LIVE = "LIVE"
    LIVE_CACHE = "LIVE_CACHE"
    REPLAY = "REPLAY"
    SYNTHETIC = "SYNTHETIC"  # Explicitly fictional offline provider

class SearchStatus(str, Enum):
    OK = "OK"
    ERROR = "ERROR"

class PlannedQuery(FrozenModel):
    query: str
    purpose: QueryPurpose
    tier: QueryTier
    priority: int
    use_advanced_operators: bool = False

class OrganicResult(FrozenModel):
    @field_validator("link")
    @classmethod
    def safe_link(cls, value: str) -> str:
        try:
            u = urlsplit(value)
            if u.scheme.lower() not in {"http", "https"} or not u.hostname or u.username or u.password:
                raise ValueError("UNSAFE_SEARCH_URL")
            hostname = u.hostname.casefold().rstrip(".")
            # RFC-informal numeric IPv4 forms can resolve to local addresses in browsers.
            import re
            if (re.fullmatch(r"[0-9]+", hostname) or re.fullmatch(r"0x[0-9a-f]+", hostname)
                    or (re.fullmatch(r"0[0-7]+", hostname) and len(hostname) > 2)):
                raise ValueError("PRIVATE_SEARCH_URL")
            import socket
            try:
                legacy_ip = ipaddress.ip_address(socket.inet_aton(hostname))
            except (OSError, ValueError):
                legacy_ip = None
            if legacy_ip is not None and not legacy_ip.is_global:
                raise ValueError("PRIVATE_SEARCH_URL")
            try:
                ip = ipaddress.ip_address(u.hostname)
                if not ip.is_global:
                    raise ValueError("PRIVATE_SEARCH_URL")
            except ValueError as exc:
                if str(exc) == "PRIVATE_SEARCH_URL":
                    raise
        except ValueError:
            raise ValueError("UNSAFE_SEARCH_URL") from None
        return value

    position: int | None = None
    title: str | None = None
    link: str
    snippet: str | None = None
    displayed_link: str | None = None

class SearchResponse(FrozenModel):
    query: PlannedQuery
    mode: SearchMode
    status: SearchStatus
    captured_at: datetime
    search_id: str | None = None
    results: tuple[OrganicResult, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    # Monotonic wall time for this one provider attempt. Never includes a URL,
    # credential, or upstream response body.
    elapsed_ms: int | None = Field(default=None, ge=0)
    timeout_kind: str | None = None
    response_sha256: str | None = None
    provider_cached: bool | None = None
    provider_status: str | None = None
    request_parameters: tuple[tuple[str, str], ...] = ()

class SearchManifestEntry(FrozenModel):
    query: str
    purpose: QueryPurpose
    tier: QueryTier
    mode: SearchMode
    status: SearchStatus
    captured_at: datetime
    search_id: str | None = None
    response_sha256: str | None = None
    result_count: int = 0
    provider_cached: bool | None = None
    provider_status: str | None = None
    # A controlled adapter code, never an upstream diagnostic or credential.
    # Persist it so an incomplete live run remains diagnosable without replaying
    # paid searches or exposing provider response bodies.
    error_code: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    timeout_kind: str | None = None
    request_parameters: tuple[tuple[str, str], ...] = ()

class SearchPlan(FrozenModel):
    queries: tuple[PlannedQuery, ...]
    max_calls: int = 8
    localization_items: tuple[tuple[str, str], ...] = (("gl", "in"), ("hl", "en"))

    @model_validator(mode="before")
    @classmethod
    def immutable_localization(cls, value):
        if isinstance(value, dict) and "localization" in value:
            value = dict(value)
            loc = value.pop("localization")
            if not isinstance(loc, dict):
                raise ValueError("localization must be mapping")
            value["localization_items"] = tuple(sorted((str(k), str(v)) for k, v in loc.items()))
        return value

    @property
    def localization(self):
        from types import MappingProxyType
        return MappingProxyType(dict(self.localization_items))
