"""Canonical, fail-closed field value equivalence. Never compare repr(value)."""
from __future__ import annotations
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from .enums import CriticalField
from .normalization import canonicalize_url, canonical_scope_value

class UnsupportedValue(ValueError):
    pass

def canonical_value(field: CriticalField, value: object):
    if value is None or isinstance(value, (dict, list, set, tuple)):
        raise UnsupportedValue("UNSUPPORTED_VALUE")
    if field == CriticalField.DEADLINE:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise UnsupportedValue("AMBIGUOUS_TIMEZONE")
            return ("deadline_instant", value.astimezone(timezone.utc).isoformat())
        if isinstance(value, date):
            return ("deadline_date", value.isoformat())
        if isinstance(value, str):
            try:
                # ISO date; preserve date-only precision.
                if len(value.strip()) == 10:
                    return ("deadline_date", date.fromisoformat(value.strip()).isoformat())
                parsed = datetime.fromisoformat(value.strip())
                if parsed.tzinfo is None:
                    raise UnsupportedValue("AMBIGUOUS_TIMEZONE")
                return ("deadline_instant", parsed.astimezone(timezone.utc).isoformat())
            except (ValueError, TypeError):
                raise UnsupportedValue("AMBIGUOUS_DATE") from None
        raise UnsupportedValue("INVALID_DEADLINE")
    if field in {CriticalField.FEE, CriticalField.REWARD} and isinstance(value, str):
        s = value.strip()
        m = re.fullmatch(r"(?i)(INR|USD|EUR|GBP|₹|Rs\.?)\s*([0-9]+(?:\.[0-9]+)?)", s)
        if m:
            currency = m.group(1).upper()
            currency = "INR" if currency in {"₹", "RS", "RS."} else currency
            return ("money", currency, Decimal(m.group(2)).normalize())
    if field in {CriticalField.FEE, CriticalField.REWARD, CriticalField.MIN_AGE,
                 CriticalField.MAX_AGE, CriticalField.MIN_EXPERIENCE_YEARS, CriticalField.TEAM_SIZE}:
        if isinstance(value, bool):
            raise UnsupportedValue("INVALID_NUMERIC")
        try:
            amount = Decimal(str(value).strip())
            if not amount.is_finite():
                raise UnsupportedValue("NONFINITE")
            return ("number", amount.normalize())
        except (InvalidOperation, ValueError):
            raise UnsupportedValue("AMBIGUOUS_NUMERIC") from None
    if field == CriticalField.APPLICATION_URL:
        try:
            return ("url", canonicalize_url(str(value)))
        except ValueError:
            raise UnsupportedValue("INVALID_URL") from None
    if isinstance(value, str):
        return ("text", canonical_scope_value(value))
    raise UnsupportedValue("UNSUPPORTED_FIELD_VALUE")

def equivalent(field: CriticalField, left: object, right: object) -> bool:
    a, b = canonical_value(field, left), canonical_value(field, right)
    if field in {CriticalField.FEE, CriticalField.REWARD} and a[0] != b[0]:
        # A bare amount cannot be treated as USD/INR (or as a proven change).
        # Require currency on both sides of a currency-bearing comparison.
        raise UnsupportedValue("CURRENCY_CONTEXT_MISSING")
    if field == CriticalField.DEADLINE and a[0] != b[0]:
        # A date-only claim and a same-day timed claim are compatible, not a proven drift.
        # Keep local calendar-date precision when one source did not state the hour.
        timed = left if isinstance(left, datetime) else right if isinstance(right, datetime) else None
        dated = left if isinstance(left, date) and not isinstance(left, datetime) else right if isinstance(right, date) and not isinstance(right, datetime) else None
        if timed is None:
            timed_raw = left if a[0] == "deadline_instant" else right
            timed = datetime.fromisoformat(timed_raw) if isinstance(timed_raw, str) else None
        if dated is None:
            raw_date = left if a[0] == "deadline_date" else right
            dated = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
        # India-primary v1: interpret an aware instant in IST for a date-only notice.
        # A future multi-country release must provide the notice's explicit civil timezone.
        return bool(timed and dated and timed.astimezone(ZoneInfo("Asia/Kolkata")).date() == dated)
    return a == b
