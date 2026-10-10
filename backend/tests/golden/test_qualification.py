from app.domain import *


def test_complex_qualification_case(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    post_a = Scope(kind=ScopeKind.POST, values=("Post A",))
    post_b = Scope(kind=ScopeKind.POST, values=("Post B",))

    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [
        a("orig", CriticalField.DEADLINE, "2026-10-01"),
        a("orig", CriticalField.FEE, 500),
    ], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-15")], issued_day=4)
    fee = d("fee", DocumentRole.CORRIGENDUM, [a("fee", CriticalField.FEE, 0, post_b)], issued_day=5)
    wd = d("withdraw", DocumentRole.CORRIGENDUM, [], issued_day=7)
    reopen = d("reopen", DocumentRole.REOPENING, [a("reopen", CriticalField.DEADLINE, "2026-10-20", post_a)], issued_day=9)

    events = [
        e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE, CriticalField.FEE], 1),
        e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 4, targets=("ev0",)),
        e("ev2", "fam-1", "fee", EventType.AMENDS, [CriticalField.FEE], 5, scope=post_b, targets=("ev0",)),
        e("ev3", "fam-1", "withdraw", EventType.WITHDRAWS, [], 7, withdraws=("ev1",)),
        # Model reopening as both a status event and explicit deadline amendment for the applicable scope.
        e("ev4", "fam-1", "reopen", EventType.REOPENS, [], 9, scope=post_a, targets=("ev0",)),
        e("ev5", "fam-1", "reopen", EventType.AMENDS, [CriticalField.DEADLINE], 9, scope=post_a, targets=("ev0",)),
    ]
    docs = [orig, ext, fee, wd, reopen]
    binds = [b(x.document_id) for x in docs]

    ctx_a = ResolutionContext(as_of=helpers["dt"](30), scopes={"POST": ("Post A",)})
    res_a = analyze(family, {CriticalField.DEADLINE: "2026-10-01", CriticalField.FEE: 500}, docs, events, binds, ctx_a, EvidenceCoverage.ADEQUATE)
    assert res_a.verdict == Verdict.SUPERSEDED
    vals_a = {r.field: r.value for r in res_a.field_resolutions}
    assert vals_a[CriticalField.DEADLINE] == "2026-10-20"
    assert vals_a[CriticalField.FEE] == 500

    ctx_b = ResolutionContext(as_of=helpers["dt"](30), scopes={"POST": ("Post B",)})
    res_b = analyze(family, {CriticalField.DEADLINE: "2026-10-01", CriticalField.FEE: 500}, docs, events, binds, ctx_b, EvidenceCoverage.ADEQUATE)
    assert res_b.verdict == Verdict.SUPERSEDED
    vals_b = {r.field: r.value for r in res_b.field_resolutions}
    assert vals_b[CriticalField.DEADLINE] == "2026-10-01"
    assert vals_b[CriticalField.FEE] == 0


def test_unparseable_potential_governing_source_abstains(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    scan = d("ext", DocumentRole.CORRIGENDUM, [], parser_status=ParserStatus.UNSUPPORTED, blocking_impact=BlockingImpact.POTENTIAL_GOVERNING, issued_day=10)
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1)]
    res = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, [orig, scan], events, [b("orig"), b("ext")], ResolutionContext(as_of=helpers["dt"](30)), EvidenceCoverage.ADEQUATE)
    assert res.verdict == Verdict.UNRESOLVED
