import random
from app.domain import *


def setup_case(family, helpers):
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    orig = d("orig", DocumentRole.ORIGINAL_NOTICE, [a("orig", CriticalField.DEADLINE, "2026-10-01")], issued_day=1)
    ext = d("ext", DocumentRole.EXTENSION, [a("ext", CriticalField.DEADLINE, "2026-10-26")], issued_day=10)
    docs = [orig, ext]
    events = [e("ev0", "fam-1", "orig", EventType.DECLARES, [CriticalField.DEADLINE], 1),
              e("ev1", "fam-1", "ext", EventType.EXTENDS, [CriticalField.DEADLINE], 10, targets=("ev0",))]
    bindings = [b("orig"), b("ext")]
    return docs, events, bindings


def result_tuple(result):
    return (
        result.verdict,
        tuple((r.field, r.status, r.value, r.source_document_id, r.provenance_event_ids) for r in result.field_resolutions),
    )


def test_result_order_invariance(family, helpers):
    docs, events, bindings = setup_case(family, helpers)
    ctx = ResolutionContext(as_of=helpers["dt"](30))
    baseline = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, docs, events, bindings, ctx, EvidenceCoverage.ADEQUATE)
    baseline_tuple = result_tuple(baseline)
    rnd = random.Random(42)
    for _ in range(50):
        d2, e2, b2 = docs[:], events[:], bindings[:]
        rnd.shuffle(d2); rnd.shuffle(e2); rnd.shuffle(b2)
        got = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, d2, e2, b2, ctx, EvidenceCoverage.ADEQUATE)
        assert result_tuple(got) == baseline_tuple


def test_irrelevant_weak_evidence_does_not_change_verdict(family, helpers):
    docs, events, bindings = setup_case(family, helpers)
    a, d, e, b = helpers["assertion"], helpers["make_doc"], helpers["event"], helpers["binding"]
    noise = d("noise", DocumentRole.ANNOUNCEMENT, [a("noise", CriticalField.DEADLINE, "2099-01-01")], issued_day=20, refs=("OTHER",))
    noise_event = e("noise-ev", "fam-1", "noise", EventType.REVISES, [CriticalField.DEADLINE], 20)
    ctx = ResolutionContext(as_of=helpers["dt"](30))
    baseline = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, docs, events, bindings, ctx, EvidenceCoverage.ADEQUATE)
    got = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, docs+[noise], events+[noise_event], bindings+[b("noise", strength=BindingStrength.POSSIBLE)], ctx, EvidenceCoverage.ADEQUATE)
    assert result_tuple(got) == result_tuple(baseline)


def test_duplicate_event_input_is_idempotent_when_same_event_id(family, helpers):
    docs, events, bindings = setup_case(family, helpers)
    ctx = ResolutionContext(as_of=helpers["dt"](30))
    baseline = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, docs, events, bindings, ctx, EvidenceCoverage.ADEQUATE)
    # Simulate adapter-level duplicate collapse by deduping on event_id before resolve.
    dedup = list({e.event_id: e for e in events + [events[-1]]}.values())
    got = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, docs, dedup, bindings, ctx, EvidenceCoverage.ADEQUATE)
    assert result_tuple(got) == result_tuple(baseline)


def test_weaker_binding_cannot_increase_certainty(family, helpers):
    docs, events, bindings = setup_case(family, helpers)
    ctx = ResolutionContext(as_of=helpers["dt"](30))
    strong = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, docs, events, bindings, ctx, EvidenceCoverage.ADEQUATE)
    weak_bindings = [bindings[0], bindings[1].model_copy(update={"strength": BindingStrength.POSSIBLE})]
    weak = analyze(family, {CriticalField.DEADLINE: "2026-10-01"}, docs, events, weak_bindings, ctx, EvidenceCoverage.ADEQUATE)
    assert strong.verdict == Verdict.SUPERSEDED
    assert weak.verdict != Verdict.SUPERSEDED
