from app.domain import *
from app.domain.resolver import resolve_field


def test_scope_values_are_cleaned_and_unknown_without_context():
    s = Scope(kind=ScopeKind.POST, values=(" Post A ", "", "Post B"))
    assert s.values == ("Post A", "Post B")
    assert s.applies_to(ResolutionContext(as_of=__import__('datetime').datetime.now(__import__('datetime').timezone.utc))) is None


def test_event_effective_until_and_inactive_status(helpers):
    e = helpers["event"]("ev", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1)
    e = e.model_copy(update={"effective_until": helpers["dt"](5)})
    assert e.is_effective(helpers["dt"](4)) is True
    assert e.is_effective(helpers["dt"](6)) is False
    e2 = e.model_copy(update={"status": EventStatus.WITHDRAWN})
    assert e2.is_effective(helpers["dt"](4)) is False


def test_binding_with_no_identity_is_rejected(family, helpers):
    d = helpers["make_doc"]("d", DocumentRole.UNKNOWN, issuer=None, refs=())
    assert bind_document(d, family).strength == BindingStrength.REJECTED


def test_multiple_declaration_values_conflict(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [
        a("orig", CriticalField.DEADLINE, "2026-10-01"),
        a("orig", CriticalField.DEADLINE, "2026-10-02"),
    ], issued_day=1)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1)]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig], events, [b("orig")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.CONFLICT


def test_declaration_without_field_is_unresolved(family, helpers):
    d, e, b = helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [], issued_day=1)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [], 1)]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig], events, [b("orig")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.UNRESOLVED


def test_governing_event_without_assertion_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
        e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("ev0",)),
    ]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig, ext], events, [b("orig"), b("ext")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.UNRESOLVED


def test_governing_event_with_multiple_values_conflicts(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [
        a("ext", CriticalField.DEADLINE, "2026-10-15"),
        a("ext", CriticalField.DEADLINE, "2026-10-20"),
    ], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
        e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("ev0",)),
    ]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig, ext], events, [b("orig"), b("ext")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.CONFLICT


def test_full_replacement_with_multiple_values_conflicts(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.FEE, 500)], issued_day=1)
    repl = d("ext", DocumentRole.REVISED_NOTICE, [a("ext", CriticalField.FEE, 0), a("ext", CriticalField.FEE, 100)], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.FEE], 1),
        e("ev1", "fam-1", "ext", EventType.SUPERSEDES, [CriticalField.FEE], 5, replacement=ReplacementScope.FULL, targets=("ev0",)),
    ]
    res = analyze(family, {CriticalField.FEE: 500}, [orig, repl], events, [b("orig"), b("ext")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.CONFLICT


def test_update_targeting_unresolved_parent_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    bad = d("ext", DocumentRole.EXTENSION, [], issued_day=5)
    nextd = d("fee", DocumentRole.EXTENSION, [a("fee", CriticalField.DEADLINE, "2026-10-20")], issued_day=6)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
        e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("ev0",)),
        e("ev2", "fam-1", "fee", EventType.EXTENDS, [CriticalField.DEADLINE], 6, targets=("ev1",)),
    ]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig, bad, nextd], events, [b("orig"), b("ext"), b("fee")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.UNRESOLVED


def test_nonrelevant_chain_can_reach_relevant_parent(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01"), a("orig", CriticalField.FEE, 500)], issued_day=1)
    fee = d("fee", DocumentRole.CORRIGENDUM, [a("fee", CriticalField.FEE, 0)], issued_day=3)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-20")], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE, CriticalField.FEE], 1),
        e("evfee", "fam-1", "fee", EventType.AMENDS, [CriticalField.FEE], 3, targets=("ev0",)),
        e("evext", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("evfee",)),
    ]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig, fee, ext], events, [b("orig"), b("fee"), b("ext")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.SUPERSEDED
    assert res.field_resolutions[0].value == "2026-10-20"


def test_unknown_scope_cancellation_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    cancel = d("cancel", DocumentRole.CANCELLATION, [], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
        e("ev1", "fam-1", "cancel", EventType.CANCELS, [], 5, scope=Scope(kind=ScopeKind.UNKNOWN), targets=("ev0",)),
    ]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig, cancel], events, [b("orig"), b("cancel")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.UNRESOLVED


def test_full_cancellation_without_lineage_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    cancel = d("cancel", DocumentRole.CANCELLATION, [], issued_day=5)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1), e("ev1", "fam-1", "cancel", EventType.CANCELS, [], 5)]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig, cancel], events, [b("orig"), b("cancel")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.UNRESOLVED


def test_full_cancellation_missing_target_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    cancel = d("cancel", DocumentRole.CANCELLATION, [], issued_day=5)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1), e("ev1", "fam-1", "cancel", EventType.CANCELS, [], 5, targets=("missing",))]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig, cancel], events, [b("orig"), b("cancel")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.UNRESOLVED


def test_direct_resolve_field_missing_document_is_unresolved(family, helpers):
    e, b = helpers["event"], helpers["binding"]
    event = e("ev0", "fam-1", "missing-doc", EventType.DECLARES, [CriticalField.DEADLINE], 1)
    r = resolve_field(CriticalField.DEADLINE, {}, [event], {"missing-doc": b("missing-doc")}, ResolutionContext(as_of=helpers["dt"](30)))
    assert r.status == FieldResolutionStatus.UNRESOLVED


def test_relevant_update_targeting_declaration_without_field_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.FEE, 500)], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-20")], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.FEE], 1),
        e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("ev0",)),
    ]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig, ext], events, [b("orig"), b("ext")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.UNRESOLVED


def test_relevant_update_targeting_nonrelevant_event_without_lineage_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    orphan_fee = d("fee", DocumentRole.CORRIGENDUM, [a("fee", CriticalField.FEE, 0)], issued_day=3)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-20")], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
        e("evfee", "fam-1", "fee", EventType.AMENDS, [CriticalField.FEE], 3),
        e("evext", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("evfee",)),
    ]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig, orphan_fee, ext], events, [b("orig"), b("fee"), b("ext")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.UNRESOLVED


def test_cycle_between_relevant_events_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    x1 = d("orig", DocumentRole.EXTENSION, [a("orig", CriticalField.DEADLINE, "2026-10-15")], issued_day=1)
    x2 = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-20")], issued_day=2)
    events = [
        e("ev0", "fam-1", "orig", EventType.EXTENDS, [CriticalField.DEADLINE], 1, targets=("ev1",)),
        e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 2, targets=("ev0",)),
    ]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [x1, x2], events, [b("orig"), b("ext")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.UNRESOLVED
