"""v0.7 candidate discovery → captured sources → grounded event → resolver.

Safety scope: explicit English notice deadlines, extensions and full cancellations.
Issuer-host attestations must be curated out-of-band by the application operator.
Unknown corrections, unverified hosts, partial parsing and incomplete searches abstain.
"""
from __future__ import annotations
from datetime import timezone, datetime, timedelta
from hashlib import sha256
from urllib.parse import urlsplit, unquote, urldefrag
import re
import asyncio
import tempfile
from pathlib import Path
from app.domain.binding import bind_document
from app.domain.enums import (
    CriticalField, DocumentRole, EventType, EvidenceCoverage, Verdict,
    BlockingImpact, BindingStrength,
)
from app.domain.models import GovernanceEvent, NoticeFamily, NoticeIdentity, ResolutionContext
from app.domain.resolver import analyze
from app.search.models import SearchStatus, SearchMode
from app.search.planner import plan_queries
from app.domain.normalization import normalize_reference
from app.search.models import QueryTier
from app.search.manifest import to_manifest_entry
from app.sources import (
    IssuerAuthorityRegistry, SafeSourceFetcher, SourceFailure,
    ground_exact_quote, admit_document, parse_snapshot, SnapshotStore,
)
from .extract import extract_notice, ExtractionUnresolved
from .models import NoticeCheckRequest, CheckOutcome, SourceTrace

MAX_CANDIDATES = 12


def _material_external_lead(result, req, update_words) -> bool:
    """Identify a specific family/update lead, never authenticate its claims.

    An update word or an issuer name alone is low-specificity noise. Match the
    complete normalized reference with token boundaries, not a shared prefix.
    Explicit contradictory issuer labels describe a different candidate family.
    Unstructured attribution, dates and quoted changes cannot establish that a
    matching lead is already resolved, duplicated or inapplicable.
    """
    text = normalize_reference(' '.join((result.title or '', result.snippet or '', unquote(result.link))))
    reference = normalize_reference(req.reference_number)
    if not re.search(r'(?<![\w/-])' + re.escape(reference) + r'(?![\w/-])', text):
        return False
    if not update_words.search(text):
        return False
    labels = re.findall(r'(?im)\bissuer\s*:\s*([^;\n]+)', (result.title or '') + '\n' + (result.snippet or ''))
    if labels and all(normalize_reference(label) != normalize_reference(req.issuer_name) for label in labels):
        return False
    return True


async def _drained_thread(func, *args, **kwargs):
    """Drain an already-started worker on cancellation; no orphan work.

    Callers must still bound the underlying I/O/parse workload separately.
    """
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(task)
        except Exception:
            pass
        raise



def _unknown(family_id: str, mode: str, count: int, entries=(), sources=(), reason='UNRESOLVED_EVIDENCE', detail=None):
    from app.domain.models import AnalysisResult
    return CheckOutcome(analysis=AnalysisResult(verdict=Verdict.UNRESOLVED,
        coverage=EvidenceCoverage.INSUFFICIENT, family_id=family_id,
        warnings=(reason,)), execution_mode=mode, provider_calls=count,
        search_entries=tuple(entries), sources=tuple(sources),
        warnings=(reason, detail) if detail else (reason,))


class NoticeWorkflow:
    def __init__(self, *, executor, fetcher: SafeSourceFetcher, registry: IssuerAuthorityRegistry,
                 evidence_mode: str = "NETWORK", snapshot_store: SnapshotStore | None = None):
        if evidence_mode not in {"NETWORK", "SYNTHETIC_OFFLINE"}:
            raise ValueError("UNSUPPORTED_EVIDENCE_MODE")
        self.evidence_mode = evidence_mode
        self.executor = executor
        self.fetcher = fetcher
        self.registry = registry
        self._tempdir = None
        if snapshot_store is None:
            # Ephemeral store is for tests/offline scripts only. A live operator
            # must configure an independently protected persistent directory.
            self._tempdir = tempfile.TemporaryDirectory(prefix='noticedrift-snapshots-')
            snapshot_store = SnapshotStore(Path(self._tempdir.name))
        self.snapshot_store = snapshot_store

    async def check(self, req: NoticeCheckRequest, *, fresh: bool = True) -> CheckOutcome:
        family_id = sha256((req.issuer_id+'\x00'+req.reference_number).encode()).hexdigest()[:24]
        hosts = self.registry.approved_hosts(req.issuer_id)
        mode = self.evidence_mode + ('_FRESH_REQUESTED' if fresh else '_CACHED_REQUESTED')
        # User-requested future analysis is not equivalent to transport clock
        # skew; never certify a future as-of date.
        as_of_utc = req.as_of.astimezone(timezone.utc)
        if as_of_utc > datetime.now(timezone.utc):
            return _unknown(family_id,mode,0,reason='FUTURE_AS_OF_CANNOT_BE_CERTIFIED')
        verified_name = self.registry.issuer_label(req.issuer_id)
        if verified_name is not None and verified_name.casefold().strip() != req.issuer_name.casefold().strip():
            return _unknown(family_id,mode,0,reason='ISSUER_LABEL_NOT_MATCHED')
        if not hosts:
            return _unknown(family_id,mode,0,reason='NO_OPERATOR_VERIFIED_ISSUER_HOST')
        if self.evidence_mode == 'NETWORK' and not self.registry.live_publication_policy_ready(req.issuer_id):
            return _unknown(family_id,mode,0,reason='NO_OPERATOR_VERIFIED_PUBLICATION_SCOPE')
        # Cannot certify positive update discovery for multiple official hosts
        # when the bounded planner only carries one host-specific search.
        if len(hosts) > 1:
            return _unknown(family_id,mode,0,reason='MULTIPLE_ISSUER_HOSTS_NOT_COVERED')
        if req.original_url and (urlsplit(req.original_url).hostname not in hosts):
            return _unknown(family_id,mode,0,reason='ORIGINAL_HOST_NOT_ATTESTED')
        if req.original_url and not self.registry.verified(req.issuer_id, req.original_url):
            return _unknown(family_id,mode,0,reason='ORIGINAL_PUBLICATION_PATH_NOT_ATTESTED')
        plan = plan_queries(reference_number=req.reference_number, issuer_name=req.issuer_name,
            title=req.notice_title, official_domain=sorted(hosts)[0])
        # Validate all CORE discovery queries preserve the *entire* literal
        # notice identity. Partial-but-nonempty sanitizer output is unsafe.
        literal = normalize_reference(req.reference_number)
        core = [q for q in plan.queries if q.tier == QueryTier.CORE]
        if (len(core) < 4 or any(f'"{literal}"' not in q.query for q in core)):
            return _unknown(family_id,mode,0,reason='SEARCH_IDENTITY_NOT_PRESERVED')
        try:
            execution = await self.executor.execute(plan, fresh=fresh)
        except Exception:
            return _unknown(family_id,mode,0,reason='SEARCH_EXECUTION_FAILED')
        entries = tuple(to_manifest_entry(r) for r in execution.responses)
        if execution.coverage != EvidenceCoverage.ADEQUATE:
            return _unknown(family_id,mode,execution.attempts,entries,reason='SEARCH_COVERAGE_INADEQUATE')
        # Search snippets discover candidates, NEVER establish a governing fact.
        # Treat a specifically relevant unauthenticated hit as a coverage blocker,
        # not as authority. Unrelated internet noise cannot consume our fetch cap.
        urls = [urldefrag(req.original_url)[0]] if req.original_url else []
        external_related = False
        ordered_official: list[str] = []
        update_words = re.compile(r'(?i)\b(corrigendum|extension|extended|revised|cancel(?:led|lation)|addendum|reopening|withdrawn)\b')
        for response in execution.responses:
            if response.status != SearchStatus.OK:
                return _unknown(family_id,mode,execution.attempts,entries,reason='SEARCH_RESPONSE_FAILED')
            for result in response.results:
                url = result.link
                host = urlsplit(url).hostname
                if host not in hosts:
                    external_related |= _material_external_lead(result, req, update_words)
                    continue
                from app.sources.fetch import safe_target
                try:
                    safe_target(url)
                except SourceFailure:
                    return _unknown(family_id,mode,execution.attempts,entries,
                        reason='INVALID_SOURCE_CANDIDATE_URL')
                # Only fragments are provably irrelevant to HTTP resource
                # identity. Do not strip arbitrary query parameters.
                url = urldefrag(url)[0]
                if url in urls:
                    continue
                if url not in ordered_official and url not in urls:
                    ordered_official.append(url)
        total_candidates = len(urls) + len(ordered_official)
        source_overflow = total_candidates > MAX_CANDIDATES
        if source_overflow:
            # Search completion is not source-examination completion. Titles,
            # snippets and a proven intermediate change cannot rule out a later
            # governing document among unexamined official candidates.
            return _unknown(family_id,mode,execution.attempts,entries,
                reason='SOURCE_CANDIDATE_BUDGET_EXCEEDED')
        urls.extend(ordered_official)
        if not urls:
            return _unknown(family_id,mode,execution.attempts,entries,reason='NO_OFFICIAL_CANDIDATES')
        family = NoticeFamily(family_id=family_id, issuer_id=req.issuer_id,
            reference_aliases=frozenset({req.reference_number}),
            issuer_domains=frozenset(hosts))
        identity = NoticeIdentity(issuer_id=req.issuer_id,
            issuer_name=req.issuer_name, reference_numbers=(req.reference_number,))
        documents, extracted, traces, bindings = [], [], [], []
        captured_bytes = set()
        for url in urls:
            try:
                task = asyncio.create_task(asyncio.to_thread(self.fetcher.fetch, url, allowed_hosts=hosts))
                try:
                    snapshot = await asyncio.shield(task)
                except asyncio.CancelledError:
                    # Python cannot preempt a blocking socket/thread. Do not release
                    # request-owned work while it is still running; transport limits
                    # constrain the maximum drain duration.
                    try:
                        await asyncio.shield(task)
                    except (SourceFailure, RuntimeError, ValueError, OSError):
                        pass
                    raise
                # Redirected source must still be an independently attested exact host.
                if not self.registry.verified(req.issuer_id, snapshot.final_url):
                    raise ExtractionUnresolved('UNATTESTED_REDIRECT_HOST')
                try:
                    snapshot_id = await _drained_thread(self.snapshot_store.put, snapshot)
                except (OSError, ValueError, RuntimeError, SourceFailure):
                    return _unknown(family_id,mode,execution.attempts,entries,traces,
                        reason='EVIDENCE_PERSISTENCE_FAILED')
                if snapshot.body_sha256 in captured_bytes:
                    # Byte-identical mirrors are one document, never two originals.
                    continue
                captured_bytes.add(snapshot.body_sha256)
                # Parsing/PDF inspection is CPU-bound; never stall the ASGI loop.
                parsed = await _drained_thread(parse_snapshot, snapshot)
                try:
                    info = extract_notice(parsed, req.reference_number)
                except ExtractionUnresolved as exc:
                    # Unrelated official pages may occur in general search results.
                    # Only a fully parsed, clearly unrelated page can be ignored.
                    if (str(exc) == 'IDENTITY_OR_PARSER_UNRESOLVED'
                        and parsed.status == 'PARSED'
                        and not update_words.search(parsed.text)
                        and req.reference_number.casefold() not in parsed.text.casefold()):
                        continue
                    raise
                fields = ()
                if info.deadline_text:
                    span = ground_exact_quote(snapshot,parsed,info.deadline_text)
                    fields = ((CriticalField.DEADLINE,info.deadline_text,info.deadline,span),)
                # Ground the event itself separately from the resulting field.
                relation = ground_exact_quote(snapshot,parsed,info.relation_quote)
                did = sha256(snapshot.body).hexdigest()[:24]
                document = admit_document(snapshot, parsed, identity, did, info.role,
                    self.registry, grounded_fields=fields)
                document = type(document).model_validate({**document.model_dump(), "issued_at": info.issued_at})
                binding = bind_document(document,family)
                if binding.strength != BindingStrength.STRONG:
                    raise ExtractionUnresolved('DOCUMENT_FAMILY_NOT_STRONG')
                documents.append(document)
                bindings.append(binding)
                extracted.append((document,info,relation))
                traces.append(SourceTrace(url=snapshot.final_url,
                    source_sha256=snapshot.body_sha256, text_sha256=parsed.normalized_text_sha256,
                    role=info.role.value, issued_at=info.issued_at,
                    relation_quote=relation.quotation, quote_page=relation.page_number,
                    authority_attested=True,snapshot_id=snapshot_id))
            except (SourceFailure, ExtractionUnresolved, ValueError, RuntimeError):
                # Include the failed candidate (but never trust it as evidence).
                return _unknown(family_id,mode,execution.attempts,entries,traces,
                    reason='POTENTIALLY_GOVERNING_SOURCE_UNRESOLVED',
                    detail=urlsplit(url)._replace(query='',fragment='').geturl())
        originals = [(d,info,span) for d,info,span in extracted if info.role == DocumentRole.ORIGINAL_NOTICE]
        if len(originals) != 1:
            return _unknown(family_id,mode,execution.attempts,entries,traces,
                            reason='UNIQUE_ORIGINAL_NOT_ESTABLISHED')
        original,orig_info,original_span = originals[0]
        original_event_id = 'original-'+original.document_id
        events = [GovernanceEvent(event_id=original_event_id,family_id=family_id,
            source_document_id=original.document_id,event_type=EventType.DECLARES,
            affected_fields=frozenset({CriticalField.DEADLINE}),
            issued_at=orig_info.issued_at,evidence_text=original_span.quotation)]
        # A deterministic linear chain is allowed only when every explicit 'from' value
        # matches the previously controlling deadline. Otherwise abstain.
        current = orig_info.deadline
        predecessor = original_event_id
        predecessor_date = orig_info.issued_at
        # A causal deadline chain is defined by explicit FROM -> TO transitions,
        # never by arbitrary content hashes or same-day lexical ordering.
        pending = [(d,info,span) for d,info,span in extracted
                   if info.role != DocumentRole.ORIGINAL_NOTICE]
        # An issue date supplies neither a time nor an issuer timezone. Refuse
        # the entire possible civil-day window rather than invent UTC midnight.
        try:
            intraday_uncertain = any(info.issued_at - timedelta(hours=14) <= as_of_utc
                < info.issued_at + timedelta(days=1, hours=14) for _,info,_ in extracted)
        except OverflowError:
            return _unknown(family_id,mode,execution.attempts,entries,traces,
                reason='ISSUANCE_DATE_RANGE_UNSUPPORTED')
        if intraday_uncertain:
            return _unknown(family_id,mode,execution.attempts,entries,traces,
                reason='DATE_ONLY_ISSUANCE_INTRADAY_UNRESOLVED')
        while pending:
            eligible = [(d,info,span) for d,info,span in pending
                        if info.role == DocumentRole.CORRIGENDUM and info.previous_deadline == current]
            if not eligible and all(x[1].role == DocumentRole.CANCELLATION for x in pending) and len(pending) == 1:
                eligible = pending[:]
            if len(eligible) != 1:
                return _unknown(family_id,mode,execution.attempts,entries,traces,
                    reason='UNRESOLVED_EXTENSION_LINEAGE')
            document,info,span = eligible[0]
            pending.remove(eligible[0])
            if info.issued_at < predecessor_date:
                return _unknown(family_id,mode,execution.attempts,entries,traces,
                    reason='INVALID_EVENT_CAUSAL_CHRONOLOGY')
            if info.role == DocumentRole.CORRIGENDUM:
                event_type,fields = EventType.EXTENDS,frozenset({CriticalField.DEADLINE})
                current = info.deadline
            elif info.role == DocumentRole.CANCELLATION:
                event_type,fields = EventType.CANCELS,frozenset()
            else:
                return _unknown(family_id,mode,execution.attempts,entries,traces,
                    reason='UNSUPPORTED_GOVERNANCE_RELATION')
            eid='event-'+document.document_id
            events.append(GovernanceEvent(event_id=eid,family_id=family_id,
                source_document_id=document.document_id,event_type=event_type,
                affected_fields=fields,target_event_ids=(predecessor,),
                issued_at=info.issued_at,evidence_text=span.quotation))
            predecessor=eid
            predecessor_date=info.issued_at
        if external_related:
            return _unknown(family_id,mode,execution.attempts,entries,traces,
                reason='UNVERIFIED_RELATED_SEARCH_CANDIDATE')
        analysis=analyze(family,{CriticalField.DEADLINE:req.supplied_deadline},documents,events,bindings,
            ResolutionContext(as_of=req.as_of),execution.coverage)
        # Even an exact search cache result must not pretend to be a fresh network check.
        return CheckOutcome(analysis=analysis,execution_mode=mode,
            provider_calls=execution.attempts,search_entries=tuple(entries),sources=tuple(traces))
