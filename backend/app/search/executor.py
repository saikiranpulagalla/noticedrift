"""Enforced per-run SerpApi call budget; deterministic execution with single-flight."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from .models import PlannedQuery, SearchPlan, SearchResponse, SearchStatus, SearchMode, QueryTier
from .cache import request_key, LiveSearchCache
from .budget import SharedCreditLedger
from app.domain.enums import EvidenceCoverage

@dataclass(frozen=True)
class SearchExecution:
    responses: tuple[SearchResponse, ...]
    attempts: int
    coverage: EvidenceCoverage
    completed_purposes: frozenset[str]

class SearchExecutor:
    def __init__(self, client, cache: LiveSearchCache | None = None,
                 ledger: SharedCreditLedger | None = None, *, simulation: bool = False):
        self.client = client
        self.cache = cache
        self.ledger = ledger
        self.simulation = simulation
        self._locks: dict[str, asyncio.Lock] = {}
        self._lock_users: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def _singleflight(self, planned: PlannedQuery, key: str, params: dict):
        async with self._lock:
            lock = self._locks.setdefault(key, asyncio.Lock())
            self._lock_users[key] = self._lock_users.get(key, 0) + 1
        try:
            async with lock:
                if self.cache:
                    hit = self.cache.get(key)
                    if hit is not None:
                        return hit.model_copy(update={"query": planned}), False
                # Only the owner of a real outbound attempt reserves a credit.
                # Cache waiters must not reserve additional paid-call tokens.
                if self.ledger is not None and not await asyncio.to_thread(self.ledger.reserve):
                    return None, False
                try:
                    result = await self.client.search(planned, **params)
                except Exception:
                    result = SearchResponse(query=planned, mode=SearchMode.SYNTHETIC if self.simulation else SearchMode.LIVE,
                        captured_at=datetime.now(timezone.utc),status=SearchStatus.ERROR,error_code='PROVIDER_EXCEPTION')
                if self.cache and result.status == SearchStatus.OK:
                    self.cache.put(key, result)
                return result, True
        finally:
            # Retain the lock until *all* holders/waiters have finished.
            # Premature removal lets a third request create a second lock while
            # earlier waiters are still executing (cache stampede race).
            async with self._lock:
                users = self._lock_users.get(key, 0) - 1
                if users <= 0:
                    self._lock_users.pop(key, None)
                    if self._locks.get(key) is lock:
                        self._locks.pop(key, None)
                else:
                    self._lock_users[key] = users

    async def execute(self, plan: SearchPlan, *, fresh: bool = True,
                      allow_local_cache: bool = False) -> SearchExecution:
        """No retries: every attempted provider call consumes one of eight tokens.

        Fresh checks deliberately bypass the local cache and request `no_cache=true`.
        An explicit cached analysis can opt into local caching, but isn't fresh.
        """
        if plan.max_calls > 8 or plan.max_calls < 0:
            raise ValueError("SEARCH_BUDGET_OUT_OF_RANGE")
        params = dict(gl=plan.localization.get("gl", "in"), hl=plan.localization.get("hl", "en"),
                      no_cache=fresh)
        if plan.localization.get("location"):
            params["location"] = plan.localization["location"]
        answers: list[SearchResponse] = []
        provider_attempts = 0
        completed: set[str] = set()
        seen_keys: set[str] = set()
        # Serial execution keeps the per-run token budget trivially race-free.
        for planned in plan.queries:
            key = request_key("google", planned.query,
                              {**{k: str(v) for k, v in params.items()}, "schema": "v2"})
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if len(answers) >= plan.max_calls:
                break
            if allow_local_cache and not fresh:
                if self.cache and (hit := self.cache.get(key)) is not None:
                    response = hit.model_copy(update={"query": planned})
                else:
                    response, dispatched = await self._singleflight(planned, key, params)
                    if response is None:
                        break
                    provider_attempts += int(dispatched)
            else:
                if self.ledger is not None and not await asyncio.to_thread(self.ledger.reserve):
                    break
                provider_attempts += 1
                try:
                    response = await self.client.search(planned, **params)
                except Exception:
                    response = SearchResponse(query=planned, mode=SearchMode.SYNTHETIC if self.simulation else SearchMode.LIVE,
                        captured_at=datetime.now(timezone.utc),status=SearchStatus.ERROR,error_code='PROVIDER_EXCEPTION')
            answers.append(response)
            if response.status == SearchStatus.OK:
                completed.add(planned.purpose.value)
        required_core = {q.purpose.value for q in plan.queries if q.tier == QueryTier.CORE}
        incomplete = bool(required_core - completed) or len(answers) < len({q.query for q in plan.queries})
        admitted_modes = {SearchMode.LIVE, SearchMode.SYNTHETIC} if self.simulation else {SearchMode.LIVE}
        stale = any(r.mode not in admitted_modes or r.provider_cached is not False for r in answers)
        # The normal planner covers the three independent forms of change.
        # An identity query or a single amendment keyword is insufficient to
        # support a no-change conclusion. This is search coverage, *not* source
        # ingestion coverage, which must be intersected later.
        required_discovery = {"AMENDMENT", "EXTENSION", "CANCELLATION"}
        discovery_missing = not required_discovery.issubset(completed)
        coverage = (EvidenceCoverage.INSUFFICIENT if not answers else
                    EvidenceCoverage.PARTIAL if incomplete or stale or discovery_missing or
                    any(r.status == SearchStatus.ERROR for r in answers) else
                    EvidenceCoverage.ADEQUATE)
        # ADEQUATE HERE IS SEARCH-ONLY: source-ingestion coverage must be intersected later.
        return SearchExecution(tuple(answers), provider_attempts, coverage, frozenset(completed))
