# NoticeDrift v0.5.2 — Independent-audit repair record

## Scope
This checkpoint repairs the **unchanged v0.5.1 archive** after two independent red-team suites (15 + 12 cases). It does **not** implement HTML/PDF ingestion, live issuer authority verification, or a judge-facing product.

## Reproduction

```bash
python -m pip install -r requirements.txt
python scripts/verify_v052.py
```

All automated tests block actual outbound sockets. The verifier checks **exact unrounded** coverage from pytest-cov's JSON output, plus three additional full-suite executions. This fixes a prior verification defect in which a printed coverage FAIL did not necessarily produce a failing wrapper.

## Root-cause patches

1. **Trust and identity:** reject explicit notice-year conflicts on exact-reference binding; block positive reassurance if an otherwise strong formal issuer-labelled correction comes from an unconfirmed different host. Source-class labels and same-host checks remain insufficient for LIVE authoritative trust; actual host-issuer corroboration must be added in v0.6.
2. **Evidence admission:** reject empty input comparisons; preserve indecision in the presence of partial/unsupported potentially governing formal corrections; validate event issuance/publication against source-document chronology, parent/child causality, and missing field-change metadata before verdicts.
3. **Graph:** reject untrusted cyclic candidate events *before* graph topology; preserve event target idempotence; prevent a region/post-specific update from governing a mixed-subject result.
4. **Value semantics:** normalize date-only vs aware timestamp using explicit India-primary civil-time assumption; retain hash-based SPA route fragments; require currency carried through evidence normalization when raw fees/rewards explicitly state it. A bare number vs currency-bearing number abstains rather than claiming equality or drift.
5. **Provider state:** map SerpApi `Error`, `Processing`, `Queued`, unknown statuses to non-success; permit known `Success` + documented empty-results message; classify payloads where every organic URL was rejected as failed evidence ingestion.
6. **Search coverage:** source-agnostic search execution only; requires successful AMENDMENT, EXTENSION and CANCELLATION searches for `ADEQUATE`. The old identity-only positive assertions in two original tests were explicitly revised, because they represented an unsafe expectation.
7. **Security and concurrency:** redact embedded signed/auth query URLs in log strings, block legacy numeric loopback representations, reference-count single-flight locks until *all* waiting consumers exit, and release unused locks.
8. **Regression safety:** include all independent adversarial suites unchanged, plus v0.5.2 cross-fix tests; verify original functionality and interaction behavior three times.

## Known, intentionally unclosed limitations

- **Not a releaseable application.** No live SerpApi smoke, HTTP/PDF source fetcher, authority domain attestation, source-bytes-to-quote verification, or end-to-end orchestrator that derives effective coverage from actual parsed documents.
- Calling `analyze(... coverage=ADEQUATE)` manually is valid for offline fixtures but must never be permitted as a public API input. The future application must derive it from independent search and source-ingestion gates.
- The host-consistency check is only a conservative provisional control; it does not prove that the original host is official. An actual issuer-domain registry or verified source attribution is required before using live positive assurance.
- Money with no currency metadata is supported for legacy synthetic tests but must not be treated as globally comparable across real notices; v0.6 ingestion must explicitly require currency context.
- Date-only comparison currently assumes the **Asia/Kolkata** civil timezone for this India-focused MVP. Multi-country source handling must establish the notice-specific zone and abstain if unavailable.
- Search-only coverage is a necessary, not sufficient, condition for any positive assurance. Google indexing is not exhaustive, even for `no_cache=true` searches.
- Tests here were run on Python **3.13.5**. GitHub Actions specifies 3.11 and 3.13, but a clean Python 3.11 run was **not** established in this runtime.
- Dependency ranges are declared, not lockfile-pinned. A clean environment/lockfile gate remains open.

## Gate decision

The **v0.5.2 OFFLINE correctness gate** may be marked PASS if the verifier passes. **v0.6 / product / submission gates remain OPEN.**
