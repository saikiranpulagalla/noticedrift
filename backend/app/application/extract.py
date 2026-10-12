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
# The supported relation is deliberately a complete, operative, whole-notice
# declaration.  These patterns identify language that instead makes the
# relation scoped or contingent; unsupported semantics must not become ALL.
SCOPE_TERMS = re.compile(
    r"(?i)\b(?:only|solely|exclusively)\s+for\b|\bfor\s+(?:applicants?|candidates?|posts?|categories|regions?|departments?|persons?)\b|\b(?:all\s+)?other\s+(?:applicants?|candidates?|posts?|categories|regions?|departments?)\b|\b(?:except\s+for|applicable\s+to)\b"
)
CONDITIONAL_TERMS = re.compile(
    r"(?i)\b(?:if|unless|subject\s+to|pending|proposed|proposal|tentative|contingent\s+on|upon)\b"
)
DOCUMENT_APPLICABILITY = re.compile(r'(?im)^\s*(?:scope|applicability|applicable|applies)\b')
HISTORICAL_DEADLINE_CONTEXT = re.compile(r"(?i)\b(?:original|previous|old|instead\s+of)\b")


def operative_qualification(text: str) -> bool:
    """Recognize unsupported recipient scope and operative legal conditions.

    These are grammatical relationships, not named regions, courts or boards.
    The supported whole-notice grammar cannot resolve their applicability.
    """
    return bool(re.search(
        r'(?im)^\s*(?:applicable\s+(?:only|solely|exclusively)\s+to\b|(?:only|solely|exclusively)\s+(?:the\s+)?'
        r'(?:candidates?|applicants?|persons?|posts?|categories|regions?)\b'
        r'|(?:this|the)\s+(?:extension|cancellation|notice|recruitment|deadline)\b'
        r'[^\n]*(?:\b(?:only\s+(?:after|when)|stayed|suspended|become\s+operative|'
        r'comes?\s+into\s+(?:force|effect)|subject\s+to|contingent\s+on)\b))', text))

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


def _relation_is_standalone(text: str, relation: re.Match[str]) -> bool:
    """Accept only an entire line containing the supported operative relation.

    The compact grammar intentionally refuses added qualifiers rather than
    guessing whether they limit the notice, a category, or effectiveness.
    """
    line_start = text.rfind('\n', 0, relation.start()) + 1
    line_end = text.find('\n', relation.end())
    if line_end < 0:
        line_end = len(text)
    before = text[line_start:relation.start()].strip()
    after = text[relation.end():line_end].strip()
    return not before and not after.strip('.;:')


def _relation_has_nearby_condition(text: str, relation: re.Match[str]) -> bool:
    """Reject a condition directly attached to an otherwise supported relation."""
    lines = text.splitlines()
    offset = 0
    for index, line in enumerate(lines):
        line_end = offset + len(line)
        if offset <= relation.start() <= line_end:
            nearby = [line]
            if index:
                nearby.append(lines[index - 1])
            if index + 1 < len(lines):
                nearby.append(lines[index + 1])
            return any(CONDITIONAL_TERMS.search(value) and (
                re.match(r'(?i)^\s*(?:if|unless|subject\s+to|pending|proposed|conditions?|effective)', value)
                or re.search(r'(?i)\b(?:deadline|extension|cancellation|recruitment|notice)\b', value)
            ) for value in nearby)
        offset = line_end + 1
    return True


def _screen_extension_deadlines(text: str, relation: re.Match[str]) -> None:
    """Reject a corrigendum whose other application-deadline claims disagree.

    The FROM date in the extension is historical.  Additional current deadline
    labels must either repeat the TO date or explicitly identify the old value.
    """
    previous = date_value(relation.group(1))
    current = date_value(relation.group(2))
    for declaration in ORIGINAL.finditer(text):
        value = date_value(declaration.group(1))
        line_start = text.rfind('\n', 0, declaration.start()) + 1
        context = text[line_start:declaration.start()]
        if value == current:
            continue
        if value == previous and HISTORICAL_DEADLINE_CONTEXT.search(context):
            continue
        raise ExtractionUnresolved("CONFLICTING_APPLICATION_DEADLINE")


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
    if operative_qualification(parsed.text):
        raise ExtractionUnresolved('OPERATIVE_QUALIFICATION_UNSUPPORTED')
    # A document-level applicability declaration need not be adjacent to the
    # operative sentence. This narrow grammar cannot establish its extent.
    if DOCUMENT_APPLICABILITY.search(parsed.text):
        raise ExtractionUnresolved("DOCUMENT_APPLICABILITY_UNSUPPORTED")
    # Attached conditions may be separated by administrative text. Only formal
    # operative declarations are screened here, not incidental "if" in help text.
    for line in parsed.text.splitlines():
        if (re.match(r'(?i)^\s*(?:conditions?|effectiveness|effective\b|(?:this|the)\s+(?:notice|recruitment|extension|cancellation))\b', line)
                and (CONDITIONAL_TERMS.search(line) or re.match(r'(?i)^\s*effective', line))):
            raise ExtractionUnresolved("DOCUMENT_EFFECTIVENESS_UNSUPPORTED")
    extended = list(EXTENSION.finditer(parsed.text))
    cancelled = list(CANCELLATION.finditer(parsed.text))
    if len(extended) == 1 and not cancelled:
        a = extended[0]
        if not _relation_is_standalone(parsed.text, a):
            raise ExtractionUnresolved("QUALIFIED_EXTENSION_UNSUPPORTED")
        if _relation_has_nearby_condition(parsed.text, a):
            raise ExtractionUnresolved("CONDITIONAL_NOTICE_UNSUPPORTED")
        _screen_extension_deadlines(parsed.text, a)
        # Preserve the complete exact relation quotation, not a keyword alone.
        return ExtractedNotice(role=DocumentRole.CORRIGENDUM, issued_at=issued_at,
            reference=reference, deadline=date_value(a.group(2)), deadline_text=a.group(2),
            previous_deadline=date_value(a.group(1)), previous_text=a.group(1),
            relation_quote=a.group(0))
    if len(cancelled) == 1 and not extended:
        relation = cancelled[0]
        if not _relation_is_standalone(parsed.text, relation):
            raise ExtractionUnresolved("QUALIFIED_CANCELLATION_UNSUPPORTED")
        if _relation_has_nearby_condition(parsed.text, relation):
            raise ExtractionUnresolved("CONDITIONAL_NOTICE_UNSUPPORTED")
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
