"""Exact quotation grounding and deliberately narrow operator-approved issuer attestation."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
import re
from hashlib import sha256
from pydantic import ValidationError
from .models import (
    SourceSnapshot, ParsedSource, EvidenceSpan, SourceFailure,
    SourceErrorCode, AuthorityAttestation,
)
from ..domain.models import NoticeDocument, NoticeIdentity, FieldAssertion
from ..domain.enums import (
    SourceClass, DocumentRole, ParserStatus, CriticalField,
    GroundingLevel, BlockingImpact, ExtractionMethod,
)
from ..domain.value_semantics import canonical_value, UnsupportedValue
from .values import grounded_canonical


def verify_span(parsed: ParsedSource, span: EvidenceSpan, snapshot: SourceSnapshot) -> bool:
    if parsed.snapshot_sha256 != snapshot.body_sha256 or span.snapshot_sha256 != snapshot.body_sha256:
        return False
    if span.text_sha256 != parsed.normalized_text_sha256:
        return False
    if not 0 <= span.start < span.end <= len(parsed.text):
        return False
    if not span.quotation or parsed.text[span.start:span.end] != span.quotation:
        return False
    if parsed.pages:
        actual_page = next((page for page,start,end in parsed.pages
                            if start <= span.start and span.end <= end), None)
        if actual_page is None or span.page_number != actual_page:
            return False
    elif span.page_number is not None:
        return False
    return True


def ground_exact_quote(snapshot: SourceSnapshot, parsed: ParsedSource,
                       quotation: str, *, start: int | None = None) -> EvidenceSpan:
    if parsed.status != 'PARSED':
        raise SourceFailure(SourceErrorCode.UNSUPPORTED_STRUCTURE)
    if not quotation or len(quotation) > 3000:
        raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION)
    if start is None:
        start = parsed.text.find(quotation)
        if start < 0 or parsed.text.find(quotation, start + 1) >= 0:
            # Ambiguous repeated quote must be identified by offset.
            raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION)
    end = start + len(quotation)
    page = next((n for n,a,b in parsed.pages if a <= start and end <= b), None)
    candidate = EvidenceSpan(snapshot_sha256=snapshot.body_sha256,
                             text_sha256=parsed.normalized_text_sha256,
                             start=start, end=end, quotation=quotation,
                             page_number=page)
    if not verify_span(parsed, candidate, snapshot):
        raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION)
    return candidate


AUTHORITY_REVIEW_MAX_AGE = timedelta(days=365)

class IssuerAuthorityRegistry:
    """Attestations MUST originate in an operator-controlled manifest, not search/notice text.

    A verified host is necessary, NOT sufficient: formal role, notice identity, and
    the actual relationship are still independently evaluated by the domain resolver.
    """
    def __init__(self, entries: tuple[AuthorityAttestation, ...] = ()):
        self._records: dict[tuple[str, str], AuthorityAttestation] = {}
        for entry in entries:
            host = _host(entry.exact_host)
            if host != entry.exact_host or not entry.verification_evidence_url.startswith('https://'):
                raise ValueError('INVALID_ATTESTATION')
            if entry.verification_method not in {'MANUAL_OFFICIAL_DIRECTORY', 'MANUAL_CROSS_LINK'}:
                raise ValueError('UNSUPPORTED_ATTESTATION_METHOD')
            key = (entry.issuer_id, host)
            if key in self._records:
                raise ValueError('DUPLICATE_ATTESTATION')
            self._records[key] = entry

    @staticmethod
    def _current(entry: AuthorityAttestation) -> bool:
        age = datetime.now(timezone.utc) - entry.verified_at.astimezone(timezone.utc)
        return -timedelta(minutes=5) <= age <= AUTHORITY_REVIEW_MAX_AGE

    @staticmethod
    def _operator_controlled_path(url: str) -> bool:
        # Deny clearly user-contributed publication areas even on an attested
        # host. Production still needs operator-reviewed publication-path policy.
        from urllib.parse import unquote
        raw = urlsplit(url).path
        # If a server, proxy, or framework performs a second decoding step,
        # %25, encoded slashes, dot segments and backslashes are ambiguous.
        # Ordinary encoded spaces are allowed; encoded path separators are not.
        if re.search(r'(?i)%(?:25|2f|5c|2e|00)', raw) or '\\' in raw:
            return False
        path = unquote(raw)
        if '%' in path or '\\' in path:
            return False
        segments = [part.casefold() for part in path.split('/') if part]
        if any(part in {'.','..'} for part in segments):
            return False
        return not bool(set(segments) & {'user-uploads','user-content','community-uploads',
                                        'reader-submissions','forum','comments','user-files'})

    def live_publication_policy_ready(self, issuer_id: str) -> bool:
        records = [entry for (issuer, _), entry in self._records.items()
                   if issuer == issuer_id and self._current(entry)]
        return (bool(records) and all(entry.canonical_issuer_name and
                                     entry.publication_path_prefixes for entry in records)
                and self.issuer_label(issuer_id) is not None)

    def issuer_label(self, issuer_id: str) -> str | None:
        names = {entry.canonical_issuer_name for (issuer, _), entry in self._records.items()
                 if issuer == issuer_id and self._current(entry) and entry.canonical_issuer_name}
        return next(iter(names)) if len(names) == 1 else None

    def verified(self, issuer_id: str, final_url: str) -> bool:
        try:
            if urlsplit(final_url).scheme.lower() != 'https':
                return False
            hostname = _host(urlsplit(final_url).hostname or '')
            entry = self._records.get((issuer_id, hostname))
            if entry is None or not self._current(entry) or not self._operator_controlled_path(final_url):
                return False
            if entry.publication_path_prefixes:
                from urllib.parse import unquote
                path = unquote(urlsplit(final_url).path)
                if not any(path == p or path.startswith(p.rstrip('/') + '/')
                           for p in entry.publication_path_prefixes):
                    return False
            return True
        except ValueError:
            return False

    def approved_hosts(self, issuer_id: str) -> frozenset[str]:
        return frozenset(host for (issuer,host),entry in self._records.items()
                         if issuer == issuer_id and self._current(entry))


def _host(host: str) -> str:
    if not host or '\\' in host or '/' in host or '@' in host or ':' in host:
        raise ValueError('INVALID_HOST')
    result = host.rstrip('.').encode('idna').decode('ascii').lower()
    if not re.fullmatch(r'[a-z0-9.-]+', result):
        raise ValueError('INVALID_HOST')
    return result


def admit_document(snapshot: SourceSnapshot, parsed: ParsedSource,
                   identity: NoticeIdentity, document_id: str, role: DocumentRole,
                   registry: IssuerAuthorityRegistry, *,
                   grounded_fields: tuple[tuple[CriticalField, str, str | int | None, EvidenceSpan], ...] = (),
                   blocking_impact: BlockingImpact = BlockingImpact.NONE) -> NoticeDocument:
    """Only exact-grounded assertions enter documents; this does NOT generate events.

    A raw source URL, search result, domain suffix or LLM suggestion cannot grant
    source_class=ISSUER_PRIMARY. Role is a candidate operator classification;
    governing-event admission additionally requires explicit relation grounding.
    """
    if parsed.snapshot_sha256 != snapshot.body_sha256:
        raise SourceFailure(SourceErrorCode.SOURCE_INTEGRITY_ERROR)
    if sha256(parsed.text.encode('utf-8')).hexdigest() != parsed.normalized_text_sha256:
        raise SourceFailure(SourceErrorCode.SOURCE_INTEGRITY_ERROR)
    # A shared official host cannot overwrite an explicit, contradictory issuer
    # declaration with the request's identity. Missing declarations still rely
    # on the operator's independently approved publication policy.
    labels = re.findall(r'(?im)^\s*(?:issued\s+by|issuer\s*:)\s*([^\n]+)', parsed.text)
    canonical = registry.issuer_label(identity.issuer_id) or identity.issuer_name
    if any(label.strip().rstrip('.').casefold() != canonical.strip().rstrip('.').casefold()
           for label in labels):
        raise SourceFailure(SourceErrorCode.UNVERIFIED_AUTHORITY)
    # This is role screening, not full governance proof. The domain still demands
    # explicit grounded events and a verified issuer/identity before any verdict.
    keywords = {
        DocumentRole.CORRIGENDUM: ('corrigendum', 'correction'),
        DocumentRole.ADDENDUM: ('addendum',),
        DocumentRole.EXTENSION: ('extension', 'extended'),
        DocumentRole.CANCELLATION: ('cancellation', 'cancelled', 'canceled'),
        DocumentRole.REOPENING: ('reopening', 'reopened'),
        DocumentRole.REVISED_NOTICE: ('revised notice', 'revised notification'),
    }
    if parsed.status == 'PARSED' and role in keywords and not any(word in parsed.text.lower() for word in keywords[role]):
        raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION)
    fields: list[FieldAssertion] = []
    for field, raw_value, normalized_value, span in grounded_fields:
        if not verify_span(parsed, span, snapshot) or parsed.status != 'PARSED':
            raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION)
        if str(raw_value) not in span.quotation:
            raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION)
        try:
            observed = grounded_canonical(field, str(raw_value))
            proposed = canonical_value(field, normalized_value)
            if observed != proposed:
                raise ValueError('FIELD_NORMALIZATION_NOT_GROUNDED')
        except (UnsupportedValue, ValueError, SourceFailure):
            raise SourceFailure(SourceErrorCode.UNGROUNDED_ASSERTION) from None
        fields.append(FieldAssertion(field=field, raw_value=str(raw_value),
                                     normalized_value=normalized_value,
                                     evidence_text=span.quotation, source_document_id=document_id,
                                     extraction_method=ExtractionMethod.DETERMINISTIC,
                                     grounding=GroundingLevel.EXPLICIT))
    status = ParserStatus(parsed.status)
    trusted = bool(identity.issuer_id and registry.verified(identity.issuer_id, snapshot.final_url))
    # No trust is asserted solely from text, title, governmental TLD or matching search result.
    source_class = SourceClass.ISSUER_PRIMARY if trusted else SourceClass.UNKNOWN
    formal_updates = {DocumentRole.CORRIGENDUM, DocumentRole.ADDENDUM, DocumentRole.EXTENSION,
                      DocumentRole.REVISED_NOTICE, DocumentRole.CANCELLATION, DocumentRole.REOPENING}
    # Incomplete formal notices must block any future *positive* assurance if later
    # strongly bound to a family, irrespective of a caller's optimistic default.
    if role in formal_updates and status != ParserStatus.PARSED:
        blocking_impact = BlockingImpact.POTENTIAL_GOVERNING
    return NoticeDocument(document_id=document_id, identity=identity,
                          source_url=snapshot.final_url, source_class=source_class,
                          document_role=role, parser_status=status,
                          blocking_impact=blocking_impact,
                          issued_at=None, published_at=None,
                          retrieved_at=snapshot.captured_at,
                          binary_sha256=snapshot.body_sha256,
                          normalized_text_sha256=parsed.normalized_text_sha256,
                          fields=tuple(fields))
