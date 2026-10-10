# v0.8.1 adversarial safety repair — 8 October 2026

## Scope and repair philosophy

Repair of the provided v0.8 ZIP, incorporating `NoticeDrift_v08_independent_failure_audit.zip` as permanent regression cases. The original 369-test suite was retained. Two historical test oracles assumed behavior now considered unsafe or outdated: an injected reference should **fail closed**, not be searched with a changed identity; malformed operator manifests should **fail closed** with controlled unconfigured state. A third red-team oracle expected UNRESOLVED *even after the reference-preservation defect was fixed*: once `ADV-OR-17/2026` is preserved verbatim and all search and source evidence is complete, the original positive-result fixture is no longer a lossy-search repro. It was updated with an explicit justification, and independent invalid-reference probes were added. All original risk-producing cases remain regression tests.

## Changes

1. **Search identity:** `plan_queries` uses a separate, allowlisted literal reference policy; `AND` or `OR` between reference segments is preserved. Invalid syntax yields no plan; an all-word two-letter reference is insufficiently distinctive. Before provider execution, the workflow verifies the exact complete reference occurs in every CORE query. No partial search-string mutation can qualify as adequate discovery.
2. **HTML:** selected root/ancestor visibility is checked, including `opacity`, `filter`, `transform`, `aria-hidden`, clipping and hidden positioning. Statistically uncertain visibility in descendants marks the document PARTIAL. Recognized `hidden`/`display:none` descendants are excluded while keeping the remainder of a simple source parseable.
3. **PDF:** small glyphs, light text, invisible rendering, later overlays and earlier possibly opaque backgrounds downgrade a source to PARTIAL. This is conservative static analysis, not a browser/PDF renderer and not a promise of universal contrast validation.
4. **Credits:** the owner elected inside the cache single-flight lock reserves the credit, and a cache hit or follower consumes no additional ledger reservation. SQLite connections are explicitly closed.
5. **API:** invalid issuer manifests fail closed. Up to four distinct live requests can run concurrently with rate admission and 2-second truthful reuse of completed results; same-payload concurrent checks share an in-flight task. Demo API is bounded by a per-process minute window. The monthly SQLite ledger is shared among server processes only when all use the same database path.
6. **Judge interface:** real-check form is visible but disabled without operator configuration; synthetic demo and manually reviewed official references stay clearly separated. HTML uses textContent for untrusted strings and no injected HTML.

## Reproduction and release gates

Run `python scripts/verify_v081.py` from the extracted `noticedrift` folder. Exact coverage must be >=95% including new adversarial paths; all tests and three stability runs must pass. `pytest` uses mocked provider transport and consumes no SerpApi credits.

## Remaining blockers

- Live provider run with operator-key and independently vetted issuer attestation.
- Actual official notice and corrigendum bytes captured, hash stored, parsed, and matched to explicit governing relations.
- Clean Python 3.11 execution on the judge environment and full browser e2e run with a configured backend.
- CSS layout and PDF backgrounds cannot be perfectly reconstructed without rendering; treat complex or uncertain presentation as UNRESOLVED.
- The current issuer-host attestation manifest is operator-owned and not externally certified by the application itself.
- The in-process API limiter is not multi-process; use a shared gateway and the SQLite credit ledger for a public multi-worker deployment.
