from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Any
from itertools import islice
from .value_semantics import equivalent, canonical_value, UnsupportedValue
from .binding import bind_document
from .models import (
    NoticeDocument, GovernanceEvent, NoticeFamily, FamilyBinding, ResolutionContext,
    FieldResolution, AnalysisResult
)
from .enums import (
    Verdict, EvidenceCoverage, CriticalField, EventType, GroundingLevel,
    BindingStrength, FieldResolutionStatus, ParserStatus, ReplacementScope, ScopeKind, SourceClass, DocumentRole, BlockingImpact,
)

UPDATE_EVENTS = {
    EventType.CORRECTS, EventType.AMENDS, EventType.EXTENDS, EventType.REVISES,
    EventType.ADDS, EventType.CANCELS, EventType.REOPENS, EventType.SUPERSEDES,
    EventType.INCORPORATES_UNCHANGED_FIELDS,
}

@dataclass(frozen=True)
class _State:
    status: FieldResolutionStatus
    value: Any = None
    source_document_id: str | None = None
    provenance: tuple[str, ...] = ()
    reason: str | None = None


def _event_time(event: GovernanceEvent):
    return event.effective_from or event.issued_at or event.published_at


def _sort_key(event: GovernanceEvent):
    t = _event_time(event)
    return (t is None, t, event.event_id)


def _sorted_events(events: Iterable[GovernanceEvent]) -> list[GovernanceEvent]:
    return sorted(events, key=_sort_key)


# Primary issuer sources with recognized formal notice roles are the only sources permitted
# to change governing state. Relationship to a family is NOT the same as authority.
_FORMAL_ROLES = {
    EventType.DECLARES: {DocumentRole.ORIGINAL_NOTICE, DocumentRole.REVISED_NOTICE},
    EventType.CORRECTS: {DocumentRole.CORRIGENDUM, DocumentRole.REVISED_NOTICE},
    EventType.AMENDS: {DocumentRole.CORRIGENDUM, DocumentRole.ADDENDUM, DocumentRole.REVISED_NOTICE, DocumentRole.REOPENING},
    EventType.EXTENDS: {DocumentRole.EXTENSION, DocumentRole.CORRIGENDUM, DocumentRole.REVISED_NOTICE},
    EventType.REVISES: {DocumentRole.REVISED_NOTICE, DocumentRole.CORRIGENDUM},
    EventType.ADDS: {DocumentRole.ADDENDUM, DocumentRole.CORRIGENDUM},
    EventType.CANCELS: {DocumentRole.CANCELLATION, DocumentRole.CORRIGENDUM},
    EventType.REOPENS: {DocumentRole.REOPENING, DocumentRole.CORRIGENDUM},
    EventType.SUPERSEDES: {DocumentRole.REVISED_NOTICE},
    EventType.WITHDRAWS: {DocumentRole.CORRIGENDUM, DocumentRole.CANCELLATION, DocumentRole.REVISED_NOTICE},
    EventType.INCORPORATES_UNCHANGED_FIELDS: {DocumentRole.REVISED_NOTICE, DocumentRole.CORRIGENDUM},
}


def _governing_eligible(e: GovernanceEvent, documents: dict[str, NoticeDocument],
                        bindings: dict[str, FamilyBinding]) -> bool:
    doc = documents.get(e.source_document_id)
    bound = bindings.get(e.source_document_id)
    return bool(doc and bound and bound.strength == BindingStrength.STRONG
                and doc.source_class == SourceClass.ISSUER_PRIMARY
                and doc.document_role in _FORMAL_ROLES.get(e.event_type, set())
                and doc.parser_status == ParserStatus.PARSED
                and e.grounding == GroundingLevel.EXPLICIT
                and bool(e.evidence_text.strip()))


def _topological_events(events: Iterable[GovernanceEvent]) -> list[GovernanceEvent]:
    """Order by dependency edges before timestamp/ID; reject cycles."""
    by_id = {e.event_id: e for e in events}
    result, visited, visiting = [], set(), set()
    def visit(event_id):
        if event_id in visited:
            return
        if event_id in visiting:
            raise ValueError("EVENT_CYCLE")
        visiting.add(event_id)
        e = by_id[event_id]
        for target in sorted((*e.target_event_ids, *e.withdraws_event_ids)):
            if target in by_id:
                visit(target)
        visiting.remove(event_id)
        visited.add(event_id)
        result.append(e)
    for e in _sorted_events(by_id.values()):
        visit(e.event_id)
    return result


def _build_active_event_set(events: Iterable[GovernanceEvent], as_of,
                            documents: dict[str, NoticeDocument] | None = None,
                            bindings: dict[str, FamilyBinding] | None = None,
                            context: ResolutionContext | None = None
                            ) -> tuple[dict[str, GovernanceEvent], set[str], bool]:
    all_events = [e for e in events if not (documents is not None and bindings is not None
                  and not _governing_eligible(e, documents, bindings))]
    try:
        _topological_events(all_events)
    except ValueError:
        return {}, set(), True
    valid: dict[str, GovernanceEvent] = {}
    unresolved = False
    for e in all_events:
        if not e.is_effective(as_of) or e.grounding != GroundingLevel.EXPLICIT:
            continue
        if documents is not None and bindings is not None and not _governing_eligible(e, documents, bindings):
            continue
        if context is not None:
            applies = e.target_scope.applies_to(context)
            if applies is None:
                if e.event_type != EventType.DECLARES:
                    unresolved = True
                continue
            if applies is False:
                continue
        valid[e.event_id] = e
    # Missing/illegal withdrawal target is an ambiguity, never permission to deactivate.
    incoming: dict[str, set[str]] = defaultdict(set)
    for e in valid.values():
        if e.event_type != EventType.WITHDRAWS:
            continue
        if not e.withdraws_event_ids:
            unresolved = True
        for target_id in e.withdraws_event_ids:
            target = valid.get(target_id)
            if target is None or _event_time(e) is None or _event_time(target) is None or _event_time(e) < _event_time(target):
                unresolved = True
                continue
            incoming[target_id].add(e.event_id)
    active_cache: dict[str, bool] = {}
    visiting: set[str] = set()
    def is_active(eid: str) -> bool:
        nonlocal unresolved
        if eid in active_cache:
            return active_cache[eid]
        if eid in visiting:
            unresolved = True
            return False
        visiting.add(eid)
        active = not any(is_active(attacker) for attacker in sorted(incoming[eid]))
        visiting.remove(eid)
        active_cache[eid] = active
        return active
    for eid in sorted(valid):
        is_active(eid)
    withdrawn = {eid for eid, state in active_cache.items() if not state}
    active = {eid: e for eid, e in valid.items() if active_cache[eid] and e.event_type != EventType.WITHDRAWS}
    return active, withdrawn, unresolved


def _event_applies(event: GovernanceEvent, context: ResolutionContext) -> bool | None:
    return event.target_scope.applies_to(context)


def _explicit_assertions(document: NoticeDocument, field: CriticalField, context: ResolutionContext):
    out = []
    for a in document.fields:
        if a.field != field or a.grounding != GroundingLevel.EXPLICIT:
            continue
        applies = a.scope.applies_to(context)
        if applies is True:
            out.append(a)
    return out


def _is_relevant_to_field(event: GovernanceEvent, field: CriticalField, document: NoticeDocument, context: ResolutionContext) -> bool:
    if event.event_type == EventType.DECLARES:
        return bool(_explicit_assertions(document, field, context))
    if event.event_type == EventType.SUPERSEDES and event.replacement_scope == ReplacementScope.FULL:
        return True
    return field in event.affected_fields


def _nearest_relevant_targets(
    event: GovernanceEvent,
    relevant_ids: set[str],
    all_events: dict[str, GovernanceEvent],
    active_ids: set[str],
) -> tuple[set[str], bool]:
    """Return nearest relevant ancestors and whether lineage is unresolved.

    Traversal through non-relevant active events is allowed. A missing/withdrawn target makes
    lineage unresolved; this is intentionally conservative.
    """
    if event.event_type == EventType.DECLARES:
        return set(), False
    if not event.target_event_ids:
        return set(), True

    found: set[str] = set()
    unresolved = False
    stack = list(dict.fromkeys(event.target_event_ids))
    seen: set[str] = set()
    while stack:
        target_id = stack.pop()
        if target_id in seen:
            unresolved = True
            continue
        seen.add(target_id)
        target = all_events.get(target_id)
        if target is None or target_id not in active_ids:
            unresolved = True
            continue
        if target_id in relevant_ids:
            found.add(target_id)
            continue
        if target.event_type == EventType.DECLARES:
            # A declaration without this field cannot provide a field lineage.
            unresolved = True
            continue
        if not target.target_event_ids:
            unresolved = True
            continue
        stack.extend(target.target_event_ids)
    return found, unresolved


def resolve_field(
    field: CriticalField,
    documents: dict[str, NoticeDocument],
    events: Iterable[GovernanceEvent],
    bindings: dict[str, FamilyBinding],
    context: ResolutionContext,
) -> FieldResolution:
    all_events = {e.event_id: e for e in events}
    active_by_id, _withdrawn, lifecycle_unknown = _build_active_event_set(
        events, context.as_of, documents, bindings, context)
    if lifecycle_unknown:
        return FieldResolution(field=field, status=FieldResolutionStatus.UNRESOLVED, reason="EVENT_LIFECYCLE_UNRESOLVED")

    eligible: dict[str, GovernanceEvent] = {}
    unknown_scope_relevant = False
    for e in active_by_id.values():
        b = bindings.get(e.source_document_id)
        if not b or b.strength != BindingStrength.STRONG:
            continue
        applies = _event_applies(e, context)
        doc = documents.get(e.source_document_id)
        if doc is None:
            continue
        relevant = _is_relevant_to_field(e, field, doc, context)
        if applies is None and relevant:
            unknown_scope_relevant = True
            continue
        if applies is True:
            eligible[e.event_id] = e

    if unknown_scope_relevant:
        return FieldResolution(field=field, status=FieldResolutionStatus.UNRESOLVED,
                               reason="UNKNOWN_APPLICABILITY_SCOPE")

    relevant_ids = {
        eid for eid, e in eligible.items()
        if _is_relevant_to_field(e, field, documents[e.source_document_id], context)
    }
    if not relevant_ids:
        return FieldResolution(field=field, status=FieldResolutionStatus.UNRESOLVED,
                               reason="NO_GROUNDED_GOVERNING_VALUE")

    states: dict[str, _State] = {}
    parents_by_event: dict[str, set[str]] = {}
    child_count: defaultdict[str, int] = defaultdict(int)

    try:
        ordered_events = _topological_events(eligible.values())
    except ValueError:
        return FieldResolution(field=field, status=FieldResolutionStatus.UNRESOLVED, reason="EVENT_CYCLE")
    for e in ordered_events:
        if e.event_id not in relevant_ids:
            continue
        doc = documents[e.source_document_id]
        assertions = _explicit_assertions(doc, field, context)

        if e.event_type == EventType.DECLARES:
            if len(assertions) != 1:
                states[e.event_id] = _State(FieldResolutionStatus.CONFLICT if len(assertions) > 1 else FieldResolutionStatus.UNRESOLVED,
                                             provenance=(e.event_id,), reason="INVALID_DECLARATION_ASSERTIONS")
                continue
            a = assertions[0]
            states[e.event_id] = _State(FieldResolutionStatus.RESOLVED, a.normalized_value,
                                         e.source_document_id, (e.event_id,))
            parents_by_event[e.event_id] = set()
            continue

        parents, lineage_unresolved = _nearest_relevant_targets(e, relevant_ids, all_events, set(active_by_id))
        parents_by_event[e.event_id] = parents
        for p in parents:
            child_count[p] += 1

        if lineage_unresolved or not parents:
            states[e.event_id] = _State(FieldResolutionStatus.UNRESOLVED,
                                         provenance=tuple(sorted(parents)) + (e.event_id,),
                                         reason="UNRESOLVED_EVENT_LINEAGE")
            continue

        parent_states = [states.get(p) for p in parents]
        if any(ps is None or ps.status in {FieldResolutionStatus.UNRESOLVED, FieldResolutionStatus.CONFLICT} for ps in parent_states):
            states[e.event_id] = _State(FieldResolutionStatus.UNRESOLVED,
                                         provenance=tuple(sorted(parents)) + (e.event_id,),
                                         reason="UNRESOLVED_PARENT_STATE")
            continue

        try:
            parent_values = {canonical_value(field, ps.value) for ps in parent_states if ps is not None}
        except UnsupportedValue:
            return FieldResolution(field=field, status=FieldResolutionStatus.UNRESOLVED,
                                   reason="INVALID_PARENT_FIELD_VALUE")
        parent_prov = tuple(dict.fromkeys(x for ps in parent_states if ps for x in ps.provenance))

        if e.event_type == EventType.SUPERSEDES and e.replacement_scope == ReplacementScope.FULL:
            if len(assertions) == 1:
                a = assertions[0]
                states[e.event_id] = _State(FieldResolutionStatus.RESOLVED, a.normalized_value,
                                             e.source_document_id, parent_prov + (e.event_id,))
            elif len(assertions) > 1:
                states[e.event_id] = _State(FieldResolutionStatus.CONFLICT,
                                             provenance=parent_prov + (e.event_id,),
                                             reason="MULTIPLE_VALUES_IN_FULL_REPLACEMENT")
            elif e.incorporates_unchanged_fields and len(parent_values) == 1:
                ps = parent_states[0]
                states[e.event_id] = _State(FieldResolutionStatus.RESOLVED, ps.value,
                                             ps.source_document_id, parent_prov + (e.event_id,))
            else:
                states[e.event_id] = _State(FieldResolutionStatus.UNRESOLVED,
                                             provenance=parent_prov + (e.event_id,),
                                             reason="FULL_REPLACEMENT_OMITS_FIELD")
            continue

        # For ordinary field-changing events, exactly one explicit value is required.
        if field in e.affected_fields:
            if len(assertions) == 1:
                a = assertions[0]
                states[e.event_id] = _State(FieldResolutionStatus.RESOLVED, a.normalized_value,
                                             e.source_document_id, parent_prov + (e.event_id,))
            elif len(assertions) > 1:
                states[e.event_id] = _State(FieldResolutionStatus.CONFLICT,
                                             provenance=parent_prov + (e.event_id,),
                                             reason="MULTIPLE_EXPLICIT_VALUES_IN_DOCUMENT")
            else:
                states[e.event_id] = _State(FieldResolutionStatus.UNRESOLVED,
                                             provenance=parent_prov + (e.event_id,),
                                             reason="GOVERNING_EVENT_WITHOUT_GROUNDED_FIELD")

    # Relevant leaves represent competing governing branches for this field.
    leaves = [eid for eid in relevant_ids if child_count[eid] == 0 and eid in states]
    if not leaves:
        return FieldResolution(field=field, status=FieldResolutionStatus.UNRESOLVED,
                               reason="NO_GOVERNING_LEAF")

    leaf_states = [states[eid] for eid in leaves]
    if any(s.status == FieldResolutionStatus.CONFLICT for s in leaf_states):
        return FieldResolution(field=field, status=FieldResolutionStatus.CONFLICT,
                               provenance_event_ids=tuple(sorted(leaves)), reason="CONFLICTING_GOVERNING_BRANCH")
    if any(s.status == FieldResolutionStatus.UNRESOLVED for s in leaf_states):
        return FieldResolution(field=field, status=FieldResolutionStatus.UNRESOLVED,
                               provenance_event_ids=tuple(sorted(leaves)), reason="UNRESOLVED_GOVERNING_BRANCH")

    try:
        values = {canonical_value(field, s.value) for s in leaf_states}
    except UnsupportedValue:
        return FieldResolution(field=field, status=FieldResolutionStatus.UNRESOLVED,
                               reason="INVALID_GOVERNING_FIELD_VALUE")
    if len(values) > 1:
        return FieldResolution(field=field, status=FieldResolutionStatus.CONFLICT,
                               provenance_event_ids=tuple(sorted(leaves)), reason="COMPETING_GOVERNING_BRANCHES")

    # Equivalent branches are allowed; use deterministic source/provenance selection.
    chosen_id = sorted(leaves)[-1]
    chosen = states[chosen_id]
    return FieldResolution(field=field, status=FieldResolutionStatus.RESOLVED,
                           value=chosen.value, source_document_id=chosen.source_document_id,
                           provenance_event_ids=chosen.provenance)


def _full_cancelled(
    events: list[GovernanceEvent], bindings: dict[str, FamilyBinding], context: ResolutionContext,
    documents: dict[str, NoticeDocument],
) -> tuple[bool, bool]:
    """Resolve cancellation by explicit lineage, not chronological status toggling."""
    active_by_id, _, unresolved = _build_active_event_set(events, context.as_of, documents, bindings, context)
    relevant = [e for e in active_by_id.values() if e.event_type in {EventType.CANCELS, EventType.REOPENS}
                ]
    try:
        ordered = _topological_events(relevant)
    except ValueError:
        return False, True
    cancelled: set[str] = set()
    for e in ordered:
        if not e.target_event_ids:
            unresolved = True
            continue
        if e.event_type == EventType.CANCELS:
            if any(t not in active_by_id for t in e.target_event_ids):
                unresolved = True
            else:
                cancelled.add(e.event_id)
        else:
            # A reopening must explicitly target the currently active cancellation(s).
            targets = set(e.target_event_ids)
            if not (targets & cancelled):
                unresolved = True
                continue
            cancelled -= targets
    return bool(cancelled), unresolved


def analyze(
    family: NoticeFamily,
    input_fields: dict[CriticalField, object],
    documents: Iterable[NoticeDocument],
    events: Iterable[GovernanceEvent],
    bindings: Iterable[FamilyBinding],
    context: ResolutionContext,
    coverage: EvidenceCoverage,
) -> AnalysisResult:
    try:
        # Pydantic model_copy(update=...) deliberately bypasses validation; revalidate
        # at the trusted analysis boundary so fabricated nested values cannot enter.
        # Bounds apply before materialization, including to lazy/infinite iterables.
        docs_input = [NoticeDocument.model_validate(d.model_dump()) for d in islice(documents, 41)]
        events_input = [GovernanceEvent.model_validate(e.model_dump()) for e in islice(events, 161)]
        binding_input = [b for b in islice(bindings, 4097) if b.family_id == family.family_id]
    except (ValueError, TypeError):
        return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage, family_id=family.family_id,
                              warnings=("INVALID_EVIDENCE_MODEL",))
    if (len(docs_input) > 40 or len(events_input) > 160 or len(binding_input) > 80
        or len(input_fields) > 16 or len(family.reference_aliases) > 32):
        return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage, family_id=family.family_id,
                              warnings=("EVIDENCE_BUDGET_EXCEEDED",))
    if (len({d.document_id for d in docs_input}) != len(docs_input)
        or len({b.document_id for b in binding_input}) != len(binding_input)
        or len({e.event_id for e in events_input}) != len(events_input)):
        return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage, family_id=family.family_id,
                              warnings=("DUPLICATE_EVIDENCE_IDENTIFIER",))
    if not input_fields:
        return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage,
                              family_id=family.family_id, warnings=("NO_COMPARABLE_INPUT_FIELDS",))
    docs = {d.document_id: d for d in docs_input}
    binds = {b.document_id: b for b in binding_input}
    from urllib.parse import urlsplit
    authority_block = False
    original_hosts = {urlsplit(d.source_url).hostname for d in docs.values()
                      if d.document_role == DocumentRole.ORIGINAL_NOTICE
                      and d.source_class == SourceClass.ISSUER_PRIMARY
                      and d.document_id in binds and binds[d.document_id].strength == BindingStrength.STRONG}
    for did, b in list(binds.items()):
        # A verified domain allowlist takes precedence over caller-provided source_class.
        if did in docs and family.issuer_domains and b.strength == BindingStrength.STRONG:
            hostname = urlsplit(docs[did].source_url).hostname
            # Strict host match only: a subdomain is not automatically issuer-controlled.
            if hostname not in family.issuer_domains:
                binds[did] = b.model_copy(update={"strength": BindingStrength.POSSIBLE,
                                                  "reasons": ("ISSUER_DOMAIN_NOT_CONFIRMED",)})
                continue
        if (did in docs and not family.issuer_domains and original_hosts
                and docs[did].document_role != DocumentRole.ORIGINAL_NOTICE
                and urlsplit(docs[did].source_url).hostname not in original_hosts
                and b.strength == BindingStrength.STRONG):
            binds[did] = b.model_copy(update={"strength": BindingStrength.POSSIBLE,
                                              "reasons": ("UNVERIFIED_ISSUER_HOST",)})
            if docs[did].source_class == SourceClass.ISSUER_PRIMARY and docs[did].document_role in {
                DocumentRole.CORRIGENDUM, DocumentRole.ADDENDUM, DocumentRole.EXTENSION,
                DocumentRole.REVISED_NOTICE, DocumentRole.CANCELLATION, DocumentRole.REOPENING,
            }:
                authority_block = True
            continue
        # Caller may request less certainty, never more than identity proves.
        if did in docs and b.strength == BindingStrength.STRONG and bind_document(docs[did], family).strength != BindingStrength.STRONG:
            binds[did] = b.model_copy(update={"strength": BindingStrength.POSSIBLE, "reasons": ("IDENTITY_UNVERIFIED",)})
    fam_events = [e for e in events_input if e.family_id == family.family_id]
    if any(e.source_document_id not in docs for e in fam_events):
        return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage, family_id=family.family_id,
                              warnings=("EVENT_SOURCE_NOT_FOUND",))

    if not any(b.strength == BindingStrength.STRONG and
               docs[b.document_id].source_class == SourceClass.ISSUER_PRIMARY
               for b in binds.values() if b.document_id in docs):
        return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage, family_id=family.family_id,
                              warnings=("No strongly bound governing source.",))

    # Admitted evidence must have internally possible chronology and field semantics.
    # Do not allow synthetic event metadata to invent a change absent from document content.
    event_lookup = {e.event_id: e for e in fam_events}
    untrusted_event_contract = False
    for e in fam_events:
        doc = docs.get(e.source_document_id)
        b = binds.get(e.source_document_id)
        if doc is None or b is None or not _governing_eligible(e, docs, binds):
            continue
        if not e.is_effective(context.as_of):
            continue
        if e.issued_at and doc.issued_at and e.issued_at < doc.issued_at:
            untrusted_event_contract = True
        if e.published_at and doc.published_at and e.published_at < doc.published_at:
            untrusted_event_contract = True
        for parent_id in e.target_event_ids:
            parent = event_lookup.get(parent_id)
            if (parent and e.issued_at and parent.issued_at
                    and e.issued_at < parent.issued_at):
                untrusted_event_contract = True
        if (e.event_type in {EventType.EXTENDS, EventType.AMENDS, EventType.CORRECTS,
                             EventType.REVISES, EventType.ADDS}
                and not e.affected_fields and bool(doc.fields)):
            untrusted_event_contract = True

    # A later incompletely parsed formal correction may withdraw/change an earlier
    # verified update; without its content the *current* state is not proven.
    parser_block = any(
        binds.get(d.document_id) and binds[d.document_id].strength == BindingStrength.STRONG
        and d.source_class == SourceClass.ISSUER_PRIMARY
        and d.parser_status in {ParserStatus.FAILED, ParserStatus.UNSUPPORTED, ParserStatus.PARTIAL}
        and (d.blocking_impact != BlockingImpact.NONE
             or any(e.source_document_id == d.document_id and e.event_type != EventType.DECLARES
                    for e in fam_events))
        for d in docs.values()
    )

    if parser_block or untrusted_event_contract or authority_block:
        return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage,
                              family_id=family.family_id,
                              warnings=(("INCOMPLETE_POTENTIAL_GOVERNING_SOURCE",) if parser_block else
                                        ("UNVERIFIED_GOVERNING_SOURCE" if authority_block else "INVALID_GOVERNANCE_EVENT_CONTRACT",)))

    # Money claimed in raw evidence must carry its currency through normalization.
    for d in docs.values():
        b = binds.get(d.document_id)
        if not b or b.strength != BindingStrength.STRONG or d.source_class != SourceClass.ISSUER_PRIMARY:
            continue
        for a in d.fields:
            if a.field not in {CriticalField.FEE, CriticalField.REWARD}:
                continue
            raw = a.raw_value.strip()
            currency_present = bool(__import__("re").search(r"(?i)(?:\b(?:USD|INR|EUR|GBP)\b|₹|\bRs\.?)", raw))
            try:
                c = canonical_value(a.field, a.normalized_value)
            except UnsupportedValue:
                currency_present = True
                c = ("unsupported",)
            if currency_present and c[0] != "money":
                return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage,
                                      family_id=family.family_id, warnings=("CURRENCY_METADATA_MISSING",))

    resolutions = tuple(
        resolve_field(field, docs, fam_events, binds, context)
        for field in input_fields.keys()
    )

    # Resolution of admitted evidence is not assurance of the current state
    # when required discovery/source examination is incomplete. Preserve an
    # established conflict, but expose no resolved governing value otherwise.
    if coverage != EvidenceCoverage.ADEQUATE:
        if any(r.status == FieldResolutionStatus.CONFLICT for r in resolutions):
            return AnalysisResult(verdict=Verdict.CONFLICT, coverage=coverage,
                                  family_id=family.family_id, field_resolutions=resolutions)
        uncertain = tuple(r.model_copy(update={
            'status': FieldResolutionStatus.UNRESOLVED, 'value': None,
            'source_document_id': None, 'reason': 'EVIDENCE_COVERAGE_INADEQUATE',
        }) for r in resolutions)
        return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage,
                              family_id=family.family_id, field_resolutions=uncertain,
                              warnings=('EVIDENCE_COVERAGE_INADEQUATE',))

    cancelled, cancel_unresolved = _full_cancelled(fam_events, binds, context, docs)
    # A changed field cannot mask incompatible evidence or an unresolved
    # potentially operative cancellation in this reusable multi-field API.
    if any(r.status == FieldResolutionStatus.CONFLICT for r in resolutions):
        return AnalysisResult(verdict=Verdict.CONFLICT, coverage=coverage,
                              family_id=family.family_id, field_resolutions=resolutions)
    active_status, _, _ = _build_active_event_set(fam_events, context.as_of, docs, binds, context)
    # A standalone reopening label is not itself an operative cancellation.
    # Preserve independently grounded, scoped amendments in that situation;
    # an unresolved applicable cancellation must still block every assurance.
    if cancel_unresolved and any(e.event_type == EventType.CANCELS for e in active_status.values()):
        uncertain = tuple(r.model_copy(update={
            'status': FieldResolutionStatus.UNRESOLVED, 'value': None,
            'source_document_id': None, 'reason': 'UNRESOLVED_GOVERNING_STATUS',
        }) for r in resolutions)
        return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage,
                              family_id=family.family_id, field_resolutions=uncertain,
                              warnings=('Cancellation/reopening lineage could not be safely established.',))
    if cancelled and not cancel_unresolved:
        return AnalysisResult(verdict=Verdict.CANCELLED, coverage=coverage, family_id=family.family_id,
                              field_resolutions=resolutions)

    changed = []
    ambiguous_comparisons = False
    for r in resolutions:
        if r.status == FieldResolutionStatus.RESOLVED and r.field in input_fields:
            try:
                if not equivalent(r.field, r.value, input_fields[r.field]):
                    changed.append(r)
            except UnsupportedValue:
                ambiguous_comparisons = True
    if changed and not ambiguous_comparisons and not any(
            r.status == FieldResolutionStatus.UNRESOLVED for r in resolutions):
        changed_ids = {r.field for r in changed}
        adjusted = tuple(
            r.model_copy(update={"status": FieldResolutionStatus.CHANGED}) if r.field in changed_ids else r
            for r in resolutions
        )
        return AnalysisResult(verdict=Verdict.SUPERSEDED, coverage=coverage, family_id=family.family_id,
                              field_resolutions=adjusted)

    if any(r.status == FieldResolutionStatus.CONFLICT for r in resolutions):
        return AnalysisResult(verdict=Verdict.CONFLICT, coverage=coverage, family_id=family.family_id,
                              field_resolutions=resolutions)

    if cancel_unresolved or parser_block or ambiguous_comparisons or any(r.status == FieldResolutionStatus.UNRESOLVED for r in resolutions):
        warnings = []
        if cancel_unresolved:
            warnings.append("Cancellation/reopening lineage could not be safely established.")
        if parser_block:
            warnings.append("A strongly bound source could not be safely parsed.")
        return AnalysisResult(verdict=Verdict.UNRESOLVED, coverage=coverage, family_id=family.family_id,
                              field_resolutions=resolutions, warnings=tuple(warnings))

    return AnalysisResult(verdict=Verdict.SUPPORTED_BY_EVIDENCE, coverage=coverage,
                          family_id=family.family_id, field_resolutions=resolutions)
