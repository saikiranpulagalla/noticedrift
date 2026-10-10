from datetime import datetime, timezone
from app.domain import *


def run(family, docs, events, bindings, input_fields, helpers, coverage=EvidenceCoverage.ADEQUATE, scopes=None, as_of_day=30):
    return analyze(
        family, input_fields, docs, events, bindings,
        ResolutionContext(as_of=helpers["dt"](as_of_day), scopes=scopes or {}), coverage,
    )


def test_future_effective_extension_does_not_apply_yet(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-10")], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-20")], issued_day=5)
    ev0 = e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1)
    ev1 = e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("ev0",))
    ev1 = ev1.model_copy(update={"effective_from": helpers["dt"](12)})
    res = run(family, [orig, ext], [ev0, ev1], [b("orig"), b("ext")], {CriticalField.DEADLINE: "2026-10-10"}, helpers, as_of_day=8)
    assert res.verdict == Verdict.SUPPORTED_BY_EVIDENCE


def test_future_effective_extension_applies_after_effective_date(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-10")], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-20")], issued_day=5)
    ev0 = e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1)
    ev1 = e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("ev0",)).model_copy(update={"effective_from": helpers["dt"](12)})
    res = run(family, [orig, ext], [ev0, ev1], [b("orig"), b("ext")], {CriticalField.DEADLINE: "2026-10-10"}, helpers, as_of_day=15)
    assert res.verdict == Verdict.SUPERSEDED
    assert res.field_resolutions[0].value == "2026-10-20"


def test_competing_extensions_from_same_parent_conflict(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    x1 = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-15")], issued_day=5)
    x2 = d("fee", DocumentRole.EXTENSION, [a("fee", CriticalField.DEADLINE, "2026-10-20")], issued_day=6)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
        e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("ev0",)),
        e("ev2", "fam-1", "fee", EventType.EXTENDS, [CriticalField.DEADLINE], 6, targets=("ev0",)),
    ]
    res = run(family, [orig, x1, x2], events, [b("orig"), b("ext"), b("fee")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.CONFLICT


def test_sequential_extension_lineage_resolves_latest(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    x1 = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-15")], issued_day=5)
    x2 = d("fee", DocumentRole.EXTENSION, [a("fee", CriticalField.DEADLINE, "2026-10-20")], issued_day=6)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
        e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("ev0",)),
        e("ev2", "fam-1", "fee", EventType.EXTENDS, [CriticalField.DEADLINE], 6, targets=("ev1",)),
    ]
    res = run(family, [orig, x1, x2], events, [b("orig"), b("ext"), b("fee")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.SUPERSEDED
    assert res.field_resolutions[0].value == "2026-10-20"


def test_full_replacement_without_incorporation_does_not_inherit_omitted_field(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.FEE, 500)], issued_day=1)
    repl = d("ext", DocumentRole.REVISED_NOTICE, [], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.FEE], 1),
        e("ev1", "fam-1", "ext", EventType.SUPERSEDES, [], 5, replacement=ReplacementScope.FULL, targets=("ev0",)),
    ]
    res = run(family, [orig, repl], events, [b("orig"), b("ext")], {CriticalField.FEE: 500}, helpers)
    assert res.verdict == Verdict.UNRESOLVED
    assert res.field_resolutions[0].reason == "UNRESOLVED_GOVERNING_BRANCH"


def test_full_replacement_can_explicitly_incorporate_unchanged_field(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.FEE, 500)], issued_day=1)
    repl = d("ext", DocumentRole.REVISED_NOTICE, [], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.FEE], 1),
        e("ev1", "fam-1", "ext", EventType.SUPERSEDES, [], 5, replacement=ReplacementScope.FULL, targets=("ev0",), incorporates=True),
    ]
    res = run(family, [orig, repl], events, [b("orig"), b("ext")], {CriticalField.FEE: 500}, helpers)
    assert res.verdict == Verdict.SUPPORTED_BY_EVIDENCE
    assert res.field_resolutions[0].value == 500


def test_full_replacement_with_explicit_new_value_supersedes(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.FEE, 500)], issued_day=1)
    repl = d("ext", DocumentRole.REVISED_NOTICE, [a("ext", CriticalField.FEE, 0)], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.FEE], 1),
        e("ev1", "fam-1", "ext", EventType.SUPERSEDES, [CriticalField.FEE], 5, replacement=ReplacementScope.FULL, targets=("ev0",)),
    ]
    res = run(family, [orig, repl], events, [b("orig"), b("ext")], {CriticalField.FEE: 500}, helpers)
    assert res.verdict == Verdict.SUPERSEDED
    assert res.field_resolutions[0].value == 0


def test_missing_event_target_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-20")], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
        e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("missing",)),
    ]
    res = run(family, [orig, ext], events, [b("orig"), b("ext")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.UNRESOLVED


def test_update_without_target_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-20")], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
        e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5),
    ]
    res = run(family, [orig, ext], events, [b("orig"), b("ext")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.UNRESOLVED


def test_partial_cancellation_does_not_cancel_other_post(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    post_b = Scope(kind=ScopeKind.POST, values=("Post B",))
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    cancel = d("cancel", DocumentRole.CANCELLATION, [], issued_day=5)
    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
        e("ev1", "fam-1", "cancel", EventType.CANCELS, [CriticalField.NOTICE_STATUS], 5, scope=post_b, targets=("ev0",)),
    ]
    res = run(family, [orig, cancel], events, [b("orig"), b("cancel")], {CriticalField.DEADLINE: "2026-10-01"}, helpers, scopes={"POST": ("Post A",)})
    assert res.verdict == Verdict.SUPPORTED_BY_EVIDENCE


def test_unrelated_unparseable_strong_source_does_not_block_positive(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    faq = d("ext", DocumentRole.FAQ, [], parser_status=ParserStatus.UNSUPPORTED, blocking_impact=BlockingImpact.NONE, issued_day=5)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1)]
    res = run(family, [orig, faq], events, [b("orig"), b("ext")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.SUPPORTED_BY_EVIDENCE


def test_no_strong_binding_is_unresolved(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1)]
    res = run(family, [orig], events, [b("orig", strength=BindingStrength.POSSIBLE)], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.UNRESOLVED
