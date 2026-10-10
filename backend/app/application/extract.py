"""Deliberately narrow, source-grounded English notice semantics.

Unsupported/cross-scoped/ambiguous corrections produce an abstention, never a guess.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import re
from app.domain.normalization import normalize_reference
from app.domain.enums import DocumentRole
from app.sources.models import ParsedSource

DATE = r"(?:\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}|\d{4}-\d{2}-\d{2})"
REF_LINE = re.compile(r"(?im)^\s*(?:Reference|Ref(?:erence)?\.?\s*(?:No\.?)?|Advertisement\s*No\.?)\s*:\s*([^\n]{1,120})\s*$")
ISSUED = re.compile(r"(?im)^\s*Issued\s*:\s*(\d{4}-\d{2}-\d{2})\s*$")
ORIGINAL = re.compile(r"(?im)\b(?:Application\s+deadline|Last\s+date)\s*:\s*(" + DATE + r")\b")
EXTENSION = re.compile(r"(?i)\b(?:the\s+)?(?:application\s+)?deadline\s+is\s+extended\s+from\s+(" + DATE + r")\s+to\s+(" + DATE + r")\b")
CANCELLATION = re.compile(r"(?i)\b(?:this\s+)?(?:recruitment|advertisement|notice)\s+is\s+cancelled\b")
CHANGE_TERMS = re.compile(r"(?i)\b(?:corrigendum|addendum|amended|modified|revised|extended|extension|withdrawn|cancelled|canceled|reopened|reopening)\b")
UNSAFE_CONTEXT = re.compile(r'(?i)\b(?:withdrawn|withdrawal|rescinded|revoked|retracted|invalidated|superseded|rumou?r|false|incorrect|not\s+(?:valid|applicable|true)|unconfirmed|alleged|claim\s+is\s+(?:false|incorrect)|quotation|quoted|reader\s+comment|speculation)\b')
SCOPE_TERMS = re.compile(r"(?i)\b(?:only\s+for|for\s+(?:post|region|category|department)|except\s+for|applicable\s+to)\b")

class ExtractionUnresolved(ValueError):
    pass

@dataclass(frozen=True)
class ExtractedNotice:
    role: DocumentRole
    issued_at: datetime
    reference: str
    deadline: date | None = None
    deadline_text: str | None = None
    previous_deadline: date | None = None
    previous_text: str | None = None
    relation_quote: str = ""


def date_value(raw: str) -> date:
    for fmt in ("%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            pass
    raise ExtractionUnresolved("UNSUPPORTED_DATE_FORMAT")


def _full_ref_match(parsed: ParsedSource, reference: str) -> bool:
    matches = REF_LINE.findall(parsed.text)
    return len(matches) == 1 and normalize_reference(matches[0]) == normalize_reference(reference)


def extract_notice(parsed: ParsedSource, reference: str) -> ExtractedNotice:
    if parsed.status != "PARSED" or not reference or not _full_ref_match(parsed, reference):
        raise ExtractionUnresolved("IDENTITY_OR_PARSER_UNRESOLVED")
    issued = ISSUED.findall(parsed.text)
    if len(issued) != 1:
        raise ExtractionUnresolved("ISSUE_DATE_UNRESOLVED")
    issued_at = datetime.combine(date_value(issued[0]), time.min, tzinfo=timezone.utc)
    if UNSAFE_CONTEXT.search(parsed.text):
        raise ExtractionUnresolved('CONTRADICTORY_OR_ATTRIBUTION_CONTEXT')
    if SCOPE_TERMS.search(parsed.text):
        raise ExtractionUnresolved("SCOPED_NOTICE_UNSUPPORTED")
    extended = list(EXTENSION.finditer(parsed.text))
    cancelled = list(CANCELLATION.finditer(parsed.text))
    if len(extended) == 1 and not cancelled:
        a = extended[0]
        # Preserve the complete exact relation quotation, not a keyword alone.
        return ExtractedNotice(role=DocumentRole.CORRIGENDUM, issued_at=issued_at,
            reference=reference, deadline=date_value(a.group(2)), deadline_text=a.group(2),
            previous_deadline=date_value(a.group(1)), previous_text=a.group(1),
            relation_quote=a.group(0))
    if len(cancelled) == 1 and not extended:
        if ORIGINAL.search(parsed.text):
            raise ExtractionUnresolved("CANCELLATION_WITH_DEADLINE_AMBIGUITY")
        return ExtractedNotice(role=DocumentRole.CANCELLATION, issued_at=issued_at,
            reference=reference, relation_quote=cancelled[0].group(0))
    if CHANGE_TERMS.search(parsed.text):
        raise ExtractionUnresolved("UNSUPPORTED_OR_AMBIGUOUS_AMENDMENT")
    found = list(ORIGINAL.finditer(parsed.text))
    if len(found) != 1:
        raise ExtractionUnresolved("ORIGINAL_DEADLINE_UNRESOLVED")
    return ExtractedNotice(role=DocumentRole.ORIGINAL_NOTICE, issued_at=issued_at,
                           reference=reference, deadline=date_value(found[0].group(1)),
                           deadline_text=found[0].group(1), relation_quote=found[0].group(0))
