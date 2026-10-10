from app.search import *


def test_reference_plan_is_bounded_and_deterministic():
    p1 = plan_queries(reference_number=" ADV / 01 / 2026 ", issuer_name="Issuer", title="Title", official_domain="example.gov", needs_emergency_expansion=True)
    p2 = plan_queries(reference_number="ADV/01/2026", issuer_name="Issuer", title="Title", official_domain="example.gov", needs_emergency_expansion=True)
    assert p1 == p2
    assert len(p1.queries) <= 8
    assert sum(q.tier == QueryTier.CORE for q in p1.queries) <= 4
    assert sum(q.tier == QueryTier.EXPANSION for q in p1.queries) <= 2
    assert sum(q.tier == QueryTier.EMERGENCY for q in p1.queries) <= 2
    assert any(q.use_advanced_operators for q in p1.queries)


def test_title_fallback_when_reference_missing():
    plan = plan_queries(reference_number=None, issuer_name="Issuer", title="Research Fellowship")
    assert len(plan.queries) == 4
    assert all(q.tier == QueryTier.CORE for q in plan.queries)
    assert plan.queries[0].purpose == QueryPurpose.IDENTITY


def test_empty_identity_produces_empty_plan():
    plan = plan_queries(reference_number=None, issuer_name=None, title=None)
    assert plan.queries == ()


def test_no_duplicate_paid_queries():
    plan = plan_queries(reference_number="ADV/01/2026", issuer_name="ADV 01 2026", title=None, needs_emergency_expansion=True)
    keys = [q.query.casefold() for q in plan.queries]
    assert len(keys) == len(set(keys))
