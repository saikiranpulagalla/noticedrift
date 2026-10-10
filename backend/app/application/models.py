from __future__ import annotations
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.domain.models import AnalysisResult
from app.search.models import SearchManifestEntry

class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')

class NoticeCheckRequest(FrozenModel):
    issuer_id: str = Field(min_length=2,max_length=120)
    issuer_name: str = Field(min_length=2,max_length=200)
    reference_number: str = Field(min_length=2,max_length=140)
    # Search-only hint, never an authority or notice-family binding assertion.
    notice_title: str | None = Field(default=None, max_length=180)
    supplied_deadline: date
    as_of: datetime
    original_url: str | None = Field(default=None, max_length=4096)

    @field_validator('original_url')
    @classmethod
    def validate_original_url(cls, v):
        if v is None:
            return v
        # Cheap validation before any billable provider attempt. Fetcher still
        # owns DNS checks, redirect checks and private-network protections.
        from app.sources.fetch import safe_target
        from app.sources.models import SourceFailure
        try:
            safe_target(v)
        except SourceFailure:
            raise ValueError('INVALID_ORIGINAL_URL') from None
        return v

    @field_validator('as_of')
    @classmethod
    def require_aware(cls, v):
        if v.utcoffset() is None:
            raise ValueError('AS_OF_MUST_BE_TIMEZONE_AWARE')
        return v

class SourceTrace(FrozenModel):
    url: str
    source_sha256: str
    text_sha256: str
    role: str
    issued_at: datetime
    relation_quote: str
    quote_page: int | None = None
    authority_attested: bool
    snapshot_id: str | None = None

class CheckOutcome(FrozenModel):
    analysis: AnalysisResult
    execution_mode: str
    provider_calls: int
    # For reused responses provider_calls is NEW calls for this HTTP request;
    # origin_provider_calls preserves the source execution's historical cost.
    origin_provider_calls: int | None = None
    search_entries: tuple[SearchManifestEntry, ...] = ()
    sources: tuple[SourceTrace, ...] = ()
    warnings: tuple[str, ...] = ()
