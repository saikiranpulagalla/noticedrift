"""Limited, evidence-anchored normalization: unsupported text MUST abstain."""
from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
import re
from ..domain.enums import CriticalField
from ..domain.value_semantics import canonical_value, UnsupportedValue
from .models import SourceFailure, SourceErrorCode

_DATE_PATTERNS = ('%Y-%m-%d', '%d %B %Y', '%d %b %Y', '%B %d, %Y', '%b %d, %Y')


def grounded_canonical(field: CriticalField, raw: str):
    raw = raw.strip()
    if field == CriticalField.DEADLINE:
        for fmt in _DATE_PATTERNS:
            try:
                return canonical_value(field, datetime.strptime(raw, fmt).date())
            except ValueError:
                continue
        raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION)
    if field in {CriticalField.FEE, CriticalField.REWARD}:
        # No guessing currency, currency conversion, ranges, 'up to', 'lakh+' or bare amounts.
        clean = raw.replace(',', '').strip()
        try:
            result = canonical_value(field, clean)
            if result[0] != 'money':
                raise ValueError()
            return result
        except (UnsupportedValue, ValueError):
            raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION) from None
    if field == CriticalField.APPLICATION_URL:
        try:
            return canonical_value(field, raw)
        except UnsupportedValue:
            raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION) from None
    if field in {CriticalField.MIN_AGE, CriticalField.MAX_AGE,
                 CriticalField.MIN_EXPERIENCE_YEARS, CriticalField.TEAM_SIZE}:
        if not re.fullmatch(r'\d+(?:\.\d+)?', raw):
            raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION)
        return canonical_value(field, Decimal(raw))
    if field in {CriticalField.LOCATION_MODE, CriticalField.NOTICE_STATUS, CriticalField.RESIDENCY}:
        return canonical_value(field, raw)
    raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION)
