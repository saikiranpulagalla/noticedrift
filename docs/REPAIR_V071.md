# v0.7.1 — Context, Visibility and Runtime Repair

This is an **offline safety checkpoint**, not independently corroborated live-site release evidence. It is based on the immutable v0.7 ZIP, with both independent audit suites imported without weakening their expectations, plus cross-fix tests.

## Trust-boundary repairs

1. **HTML authoring / visibility:** reject hidden selected roots and ancestors; remove reader comments, blockquotes and third-party discussion; understand simple stylesheet `display:none` selectors, downgrade ambiguous CSS instead of inferring visibility.
2. **PDF visible rendering:** inspect rendering mode/opacity via text traces and overlap with later opaque paint commands; if invisible, occluded or uncertain, set `PARTIAL` and block grounded decisive extraction. This is conservative, *not a general proof of visual equivalence*.
3. **Whole-document semantics:** negations, withdrawals, contradictory assertions and quoted rumor language force abstention instead of substring-driven governing actions.
4. **Search relevance:** off-domain irrelevant noise does not consume issuer candidate budget. Unverified potentially related search results block positive support. Unrelated official material with no identity/change indicators can be skipped, while suspicious/ambiguous results still abstain.
5. **Causal lineage and duplicates:** same-day updates are linked by explicit `old deadline -> new deadline` transitions rather than arbitrary hashes. Source-byte mirrors are deduplicated before requiring a unique original. Child-issued-before-parent chains abstain.
6. **Search identity:** degenerate reference sanitization aborts before using generic queries; insufficient multi-issuer-domain coverage abstains. Future `as_of` cannot be supported by today's search snapshot.
7. **Authority and redirect:** per-hop exact-host verification before fetch; future-dated operator attestations are ineligible. DNS/public-IP and TLS validation remain in place.
8. **Snapshots and audit:** captured source bytes are content-addressed and replayable through `SourceTrace.snapshot_id` while that store is available. Failed source URL and error category appear in warnings. Live mode uses an operator-local persistent store, not silent process memory.
9. **Cost and concurrency:** API checks coalesce identical requests in a disclosed 2-second window and limit distinct expensive requests per process per hour; a SQLite `SharedCreditLedger` atomically reserves SerpApi attempt budget across workers sharing its filesystem. Exhausted runs return unresolved; no silent fallback to stale evidence.
10. **Cancellation:** blocking transport threads cannot be forcibly killed safely; a cancelled request drains the bounded already-started fetch before returning cancellation. Each socket has a timeout, but a complete wall-clock bound across multi-address redirects is not yet established.

## Verification

- Original regression suite and both independent red-team suites plus cross-fix tests must all pass.
- Zero failures on the documented invisible PDF, hidden HTML, unapproved redirect, future attestation, query-degeneration, misleading quotation, multi-host and request-stampede cases.
- Exact combined branch-aware coverage must be >= 95% (unrounded).
- Three consecutive full-suite stability runs.
- Independent extraction of packaged ZIP and repeat verifier.

## Still not verified / unsupported

- Actual live SerpApi searches, real issuer ownership cross-check, and the real NCA-F notice-wording integration.
- Browsers' full CSS/layout/visibility semantics and arbitrarily complex PDFs. Such ambiguity must abstain; avoid claims of universal visual equivalence.
- Unregistered, unindexed or undiscovered changes, multi-host positive assurance, historical minute-level legal efficacy, complicated withdrawal/reopening, scoped updates, non-English and scanned PDFs.
- A global absolute fetch-runtime deadline; already-running synchronous socket work drains on cancellation.
- SQLite ledger protects only calls made through this configured application and shared ledger; other apps using the same SerpApi key consume credits outside it. Multiple instances with different ledger paths are *not* protected by one common quota.
- Clean Python 3.11 clone verification, real UI and judge demo.

## Run

```bash
python -m pip install -r requirements.txt
python scripts/verify_v071.py
```

For live (requires operator verification first): set `SERPAPI_API_KEY`, `NOTICEDRIFT_ISSUER_ATTESTATIONS`, optionally `NOTICEDRIFT_EVIDENCE_DIR` and `NOTICEDRIFT_MONTHLY_SEARCH_LIMIT` (1–250; default 200). Use shared durable storage and exactly one API admission/coordination gateway if deploying multiple workers.

The supported `SUPPORTED_BY_EVIDENCE` verdict is explicitly limited to retrieved, readable evidence; it is not proof of exhaustive web discovery.
