from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .enums import *
from .normalization import canonical_scope_value

class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

class Scope(FrozenModel):
    kind: ScopeKind = ScopeKind.ALL
    values: tuple[str, ...] = ()

    @field_validator("values")
    @classmethod
    def clean_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(v.strip() for v in values if v and v.strip())

    def applies_to(self, context: "ResolutionContext") -> bool | None:
        if self.kind == ScopeKind.ALL:
            return True
        if self.kind == ScopeKind.UNKNOWN:
            return None
        candidates = set(context.scopes.get(self.kind.value, ()))
        allowed = {canonical_scope_value(v) for v in self.values}
        if not candidates or not allowed:
            return None
        # A multi-subject check must never generalize a partial update.
        if candidates <= allowed:
            return True
        if candidates.isdisjoint(allowed):
            return False
        return None

class ResolutionContext(FrozenModel):
    as_of: datetime
    # Immutable backing representation; accept existing `scopes={...}` input for compatibility.
    scope_items: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @model_validator(mode="before")
    @classmethod
    def normalize_scopes(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if "scopes" in value:
                scopes = value.pop("scopes")
                if not isinstance(scopes, dict):
                    raise ValueError("scopes must be a mapping")
                entries = scopes.items()
            else:
                entries = value.get("scope_items", ())
            value["scope_items"] = tuple(sorted((str(k).upper(), tuple(sorted(set(
                canonical_scope_value(v) for v in vs)))) for k, vs in entries))
        return value

    @field_validator("as_of")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value

    @property
    def scopes(self) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType(dict(self.scope_items))

class NoticeIdentity(FrozenModel):
    issuer_name: str | None = None
    issuer_id: str | None = None
    reference_numbers: tuple[str, ...] = ()
    title: str | None = None
    notice_year: int | None = None

class FieldAssertion(FrozenModel):
    field: CriticalField
    raw_value: str
    normalized_value: str | int | float | bool | date | datetime | Decimal | None
    scope: Scope = Field(default_factory=Scope)
    evidence_text: str
    source_document_id: str
    extraction_method: ExtractionMethod = ExtractionMethod.DETERMINISTIC
    grounding: GroundingLevel = GroundingLevel.EXPLICIT

class NoticeDocument(FrozenModel):
    document_id: str
    identity: NoticeIdentity
    source_url: str
    source_class: SourceClass
    document_role: DocumentRole
    parser_status: ParserStatus
    blocking_impact: BlockingImpact = BlockingImpact.NONE
    issued_at: datetime | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    binary_sha256: str | None = None
    normalized_text_sha256: str
    language: str = "en"
    fields: tuple[FieldAssertion, ...] = ()

    @model_validator(mode="after")
    def validate_provenance(self):
        if any(a.source_document_id != self.document_id for a in self.fields):
            raise ValueError("FIELD_SOURCE_MISMATCH")
        return self

class GovernanceEvent(FrozenModel):
    event_id: str
    family_id: str
    source_document_id: str
    event_type: EventType
    affected_fields: frozenset[CriticalField] = frozenset()
    target_scope: Scope = Field(default_factory=Scope)
    replacement_scope: ReplacementScope = ReplacementScope.PARTIAL
    issued_at: datetime | None = None
    published_at: datetime | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    evidence_text: str
    grounding: GroundingLevel = GroundingLevel.EXPLICIT
    status: EventStatus = EventStatus.ACTIVE
    target_event_ids: tuple[str, ...] = ()
    withdraws_event_ids: tuple[str, ...] = ()
    incorporates_unchanged_fields: bool = False

    @model_validator(mode="after")
    def validate_timing(self):
        timestamps = (self.issued_at, self.published_at, self.effective_from, self.effective_until)
        if any(t is not None and (t.tzinfo is None or t.utcoffset() is None) for t in timestamps):
            raise ValueError("EVENT_TIME_MUST_BE_AWARE")
        if self.effective_from and self.effective_until and self.effective_until < self.effective_from:
            raise ValueError("INVALID_EFFECTIVE_INTERVAL")
        return self

    def is_effective(self, as_of: datetime) -> bool:
        if self.status != EventStatus.ACTIVE:
            return False
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        activated = self.effective_from or self.issued_at or self.published_at
        if activated is None or as_of < activated:
            return False
        # Later publication cannot be observed before it exists, even if retroactive effect is specified.
        if self.published_at is not None and as_of < self.published_at:
            return False
        if self.effective_from and as_of < self.effective_from:
            return False
        if self.effective_until and as_of > self.effective_until:
            return False
        return True

class NoticeFamily(FrozenModel):
    family_id: str
    issuer_id: str
    canonical_title: str | None = None
    reference_aliases: frozenset[str] = frozenset()
    issuer_domains: frozenset[str] = frozenset()  # only externally corroborated issuer domains, not first result
    notice_year: int | None = None
    document_ids: frozenset[str] = frozenset()

class FamilyBinding(FrozenModel):
    document_id: str
    family_id: str
    strength: BindingStrength
    reasons: tuple[str, ...] = ()

class FieldResolution(FrozenModel):
    field: CriticalField
    status: FieldResolutionStatus
    value: str | int | float | bool | date | datetime | Decimal | None = None
    source_document_id: str | None = None
    provenance_event_ids: tuple[str, ...] = ()
    reason: str | None = None

class AnalysisResult(FrozenModel):
    verdict: Verdict
    coverage: EvidenceCoverage
    family_id: str | None = None
    field_resolutions: tuple[FieldResolution, ...] = ()
    warnings: tuple[str, ...] = ()
