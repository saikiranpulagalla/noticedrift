from app.domain import *

def run(family, docs, events, bindings, input_fields, helpers, coverage=EvidenceCoverage.ADEQUATE, scopes=None):
    ctx = ResolutionContext(as_of=helpers["dt"](30), scopes=scopes or {})
    return analyze(family, input_fields, docs, events, bindings, ctx, coverage)

def test_deadline_extension_is_superseded(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-26")], issued_day=10)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
              e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 10, targets=("ev0",))]
    res = run(family, [orig, ext], events, [b("orig"), b("ext")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.SUPERSEDED
    assert res.field_resolutions[0].value == "2026-10-26"
    assert res.field_resolutions[0].status == FieldResolutionStatus.CHANGED

def test_withdrawal_restores_prior_value(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-15")], issued_day=5)
    wd = d("withdraw", DocumentRole.CORRIGENDUM, [], issued_day=10)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
              e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("ev0",)),
              e("ev2", "fam-1", "withdraw", EventType.WITHDRAWS, [], 10, withdraws=("ev1",))]
    res = run(family, [orig, ext, wd], events, [b("orig"), b("ext"), b("withdraw")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.SUPPORTED_BY_EVIDENCE
    assert res.field_resolutions[0].value == "2026-10-01"

def test_unknown_scope_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-20")], issued_day=5)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
              e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5, targets=("ev0",), scope=Scope(kind=ScopeKind.UNKNOWN))]
    res = run(family, [orig, ext], events, [b("orig"), b("ext")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.UNRESOLVED

def test_partial_scope_changes_only_matching_post(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.FEE, 500)], issued_day=1)
    post_b = Scope(kind=ScopeKind.POST, values=("Post B",))
    fee = d("fee", DocumentRole.CORRIGENDUM, [a("fee", CriticalField.FEE, 0, post_b)], issued_day=5)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.FEE], 1),
              e("ev1", "fam-1", "fee", EventType.AMENDS, [CriticalField.FEE], 5, scope=post_b, targets=("ev0",))]
    res_a = run(family, [orig, fee], events, [b("orig"), b("fee")], {CriticalField.FEE: 500}, helpers, scopes={"POST": ("Post A",)})
    assert res_a.verdict == Verdict.SUPPORTED_BY_EVIDENCE
    res_b = run(family, [orig, fee], events, [b("orig"), b("fee")], {CriticalField.FEE: 500}, helpers, scopes={"POST": ("Post B",)})
    assert res_b.verdict == Verdict.SUPERSEDED
    assert res_b.field_resolutions[0].value == 0

def test_full_cancellation_is_cancelled(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    cancel = d("cancel", DocumentRole.CANCELLATION, [], issued_day=5)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
              e("ev1", "fam-1", "cancel", EventType.CANCELS, [CriticalField.NOTICE_STATUS], 5, targets=("ev0",))]
    res = run(family, [orig, cancel], events, [b("orig"), b("cancel")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.CANCELLED

def test_cancellation_then_reopening_not_cancelled(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    cancel = d("cancel", DocumentRole.CANCELLATION, [], issued_day=5)
    reopen = d("reopen", DocumentRole.REOPENING, [a("reopen", CriticalField.DEADLINE, "2026-10-20")], issued_day=10)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
              e("ev1", "fam-1", "cancel", EventType.CANCELS, [CriticalField.NOTICE_STATUS], 5, targets=("ev0",)),
              e("ev2", "fam-1", "reopen", EventType.REOPENS, [CriticalField.DEADLINE], 10, targets=("ev1",))]
    res = run(family, [orig, cancel, reopen], events, [b("orig"), b("cancel"), b("reopen")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    # Reopening is proven, but deadline update needs a governing assertion path; do not falsely cancel.
    assert res.verdict == Verdict.SUPERSEDED
    assert res.field_resolutions[0].value == "2026-10-20"

def test_weak_binding_cannot_govern(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    bad = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-30")], issued_day=5)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
              e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 5)]
    res = run(family, [orig, bad], events, [b("orig"), b("ext", strength=BindingStrength.POSSIBLE)], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.SUPPORTED_BY_EVIDENCE
    assert res.field_resolutions[0].value == "2026-10-01"

def test_failed_strong_parser_blocks_positive_assurance(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    failed = d("ext", DocumentRole.CORRIGENDUM, [], parser_status=ParserStatus.UNSUPPORTED, blocking_impact=BlockingImpact.POTENTIAL_GOVERNING, issued_day=5)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1)]
    res = run(family, [orig, failed], events, [b("orig"), b("ext")], {CriticalField.DEADLINE: "2026-10-01"}, helpers)
    assert res.verdict == Verdict.UNRESOLVED

def test_partial_coverage_blocks_positive_assurance(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1)]
    res = run(family, [orig], events, [b("orig")], {CriticalField.DEADLINE: "2026-10-01"}, helpers, coverage=EvidenceCoverage.PARTIAL)
    assert res.verdict == Verdict.UNRESOLVED
