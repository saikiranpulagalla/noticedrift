from __future__ import annotations
import re
from urllib.parse import urlsplit
from .models import PlannedQuery, QueryPurpose, QueryTier, SearchPlan
from app.domain.normalization import normalize_reference

CORE_LIMIT = 4
EXPANSION_LIMIT = 2
EMERGENCY_LIMIT = 2
HARD_MAX = CORE_LIMIT + EXPANSION_LIMIT + EMERGENCY_LIMIT


def _safe_term(value: str | None, limit: int = 160) -> str:
    if not value:
        return ""
    # Drop an entire injected operator and its operand. Removing only `site:`
    # would leave the adversarial hostname behind in the discovery query.
    value = re.sub(r"(?i)\b(?:site|intitle|inurl|filetype|related|cache):\S+", " ", value)
    value = re.sub(r"[\"'(){}\[\]\r\n\t<>]", " ", value)
    value = re.sub(r"(?i)\b(?:AND|OR|NOT)\b", " ", value)
    value = re.sub(r"(?<!\S)-(?=\S)", "", value)
    return re.sub(r"\s+", " ", value).strip()[:limit].strip()

def _safe_reference(value: str | None) -> str:
    """Preserve the literal identifier; never remove internal OR/AND segments.

    Reject operator-bearing characters instead of changing the identity used
    to claim search completeness. Controlled titles still use _safe_term.
    """
    if not value:
        return ''
    literal = normalize_reference(value)
    if len(literal) > 120 or not re.fullmatch(r'[A-Z0-9][A-Z0-9._/\- ]*', literal):
        return ''
    if not any(c.isalnum() for c in literal):
        return ''
    # Two-letter all-word identifiers are too ambiguous to support a
    # positive no-change conclusion on the open web.
    if len(literal) < 4 and not any(c.isdigit() for c in literal):
        return ''
    return literal


def _q(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def _safe_domain(domain: str) -> str | None:
    try:
        parsed = urlsplit("https://" + domain)
        if (not parsed.hostname or parsed.hostname != domain.lower()
            or parsed.port is not None or parsed.username or parsed.password
            or not re.fullmatch(r"[a-z0-9.-]+", domain.lower())):
            return None
        return domain.lower()
    except ValueError:
        return None


def _reference_variant(ref: str) -> str:
    normalized = normalize_reference(ref)
    return re.sub(r"[/\-]+", " ", normalized)


def plan_queries(*, reference_number: str | None, issuer_name: str | None, title: str | None,
                 official_domain: str | None = None, needs_emergency_expansion: bool = False) -> SearchPlan:
    candidates: list[PlannedQuery] = []

    issuer_name = _safe_term(issuer_name)
    title = _safe_term(title)
    official_domain = _safe_domain(official_domain) if official_domain else None
    if reference_number:
        ref = _safe_reference(reference_number)
        if not ref:
            return SearchPlan(queries=(),max_calls=HARD_MAX)
        candidates.extend([
            PlannedQuery(query=_q(f'"{ref}"'), purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=10),
            PlannedQuery(query=_q(f'"{ref}" corrigendum'), purpose=QueryPurpose.AMENDMENT, tier=QueryTier.CORE, priority=9),
            PlannedQuery(query=_q(f'"{ref}" extension'), purpose=QueryPurpose.EXTENSION, tier=QueryTier.CORE, priority=8),
            PlannedQuery(query=_q(f'"{ref}" cancellation'), purpose=QueryPurpose.CANCELLATION, tier=QueryTier.CORE, priority=8),
        ])
        # A verified host can publish an amendment under a *different* document
        # number. Search an operator/user-provided title as a discovery HINT only.
        # Neither its results nor their ranks can satisfy the identity/authority
        # gates in the source resolver.
        if official_domain and title:
            candidates.append(PlannedQuery(
                query=_q(f'site:{official_domain} "{title}" corrigendum'),
                purpose=QueryPurpose.AMENDMENT, tier=QueryTier.EXPANSION,
                priority=7, use_advanced_operators=True))
        else:
            candidates.append(PlannedQuery(
                query=_q(f'"{_reference_variant(ref)}" {issuer_name or ""}'),
                purpose=QueryPurpose.IDENTITY, tier=QueryTier.EXPANSION, priority=7))
    elif title:
        candidates.extend([
            PlannedQuery(query=_q(f'"{title}" {issuer_name or ""}'), purpose=QueryPurpose.IDENTITY, tier=QueryTier.CORE, priority=10),
            PlannedQuery(query=_q(f'"{title}" corrigendum {issuer_name or ""}'), purpose=QueryPurpose.AMENDMENT, tier=QueryTier.CORE, priority=9),
            PlannedQuery(query=_q(f'"{title}" extension {issuer_name or ""}'), purpose=QueryPurpose.EXTENSION, tier=QueryTier.CORE, priority=8),
            PlannedQuery(query=_q(f'"{title}" cancellation {issuer_name or ""}'), purpose=QueryPurpose.CANCELLATION, tier=QueryTier.CORE, priority=8),
        ])

    if official_domain and reference_number and _safe_reference(reference_number):
        ref = _safe_reference(reference_number)
        candidates.append(PlannedQuery(
            query=_q(f'site:{official_domain} "{ref}"'), purpose=QueryPurpose.OFFICIAL_SOURCE,
            tier=QueryTier.EXPANSION, priority=7, use_advanced_operators=True,
        ))

    if needs_emergency_expansion:
        basis = _safe_reference(reference_number) if reference_number else (title or "")
        if basis:
            candidates.extend([
                PlannedQuery(query=_q(f'"{basis}" addendum'), purpose=QueryPurpose.REVISION,
                             tier=QueryTier.EMERGENCY, priority=5),
                PlannedQuery(query=_q(f'"{basis}" "last date"'), purpose=QueryPurpose.EXTENSION,
                             tier=QueryTier.EMERGENCY, priority=5),
            ])

    # Stable dedupe: query text alone determines paid-call uniqueness.
    deduped: list[PlannedQuery] = []
    seen: set[str] = set()
    tier_counts = {QueryTier.CORE: 0, QueryTier.EXPANSION: 0, QueryTier.EMERGENCY: 0}
    tier_limits = {QueryTier.CORE: CORE_LIMIT, QueryTier.EXPANSION: EXPANSION_LIMIT, QueryTier.EMERGENCY: EMERGENCY_LIMIT}
    for item in candidates:
        key = item.query.casefold()
        if key in seen or tier_counts[item.tier] >= tier_limits[item.tier]:
            continue
        seen.add(key)
        tier_counts[item.tier] += 1
        deduped.append(item)
        if len(deduped) >= HARD_MAX:
            break

    return SearchPlan(queries=tuple(deduped), max_calls=HARD_MAX)
