from pathlib import Path
import asyncio
import pytest
from app.search.budget import SharedCreditLedger
from app.search.executor import SearchExecutor
from app.search.planner import plan_queries
from test_v07_workflow import FakeSearch


def test_monthly_ledger_is_atomic_across_independent_instances(tmp_path):
    path=tmp_path/'quota.sqlite3'
    first=SharedCreditLedger(path, monthly_limit=3)
    second=SharedCreditLedger(path, monthly_limit=3)
    assert first.reserve()
    assert second.reserve()
    assert first.reserve()
    assert not second.reserve() and first.used()==3 and second.used()==3


@pytest.mark.asyncio
async def test_ledger_limits_provider_calls_not_only_per_request(tmp_path):
    client=FakeSearch([])
    ledger=SharedCreditLedger(tmp_path/'quota.sqlite3',monthly_limit=7)
    plan=plan_queries(reference_number='A/2026', issuer_name='Synthetic Issuer',title=None,
                      official_domain='issuer.example')
    executor=SearchExecutor(client,ledger=ledger)
    results=await asyncio.gather(*(executor.execute(plan,fresh=True) for _ in range(3)))
    assert sum(r.attempts for r in results)<=7
    assert len(client.calls)<=7
    assert ledger.used()<=7
    assert not all(r.coverage.value == 'ADEQUATE' for r in results)


def test_bad_quota_limit_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='INVALID_MONTHLY_CREDIT_LIMIT'):
        SharedCreditLedger(tmp_path/'x.sqlite3',monthly_limit=251)
