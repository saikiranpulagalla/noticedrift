# v0.8.2 release ledger

Version: v0.8.2 **real-world evidence readiness checkpoint**, not live promotion.

New scripts:
- `scripts/real_case_probe.py`: reviewed publisher excerpts and optional operator-provided file parsing; never produces governance decisions.
- `scripts/live_ncaf_check.py`: six bounded planned queries (dry-run default); `--execute` requires SerpApi key and operator-verified issuer manifest. No live run executed during packaging.
- `scripts/verify_v082.py`: compilation, full branch-aware test coverage exact >=95%, synthetic E2E, original suite, and three stability runs.

New independent tests: 14 cases; original 410 tests retained (total 424).

Verified locally: **424/424** tests, exact backend branch-aware coverage **95.074530%**, three stability runs, parsed publisher wording 01 Oct -> 26 Oct, dry-run provenance and zero-key refusal.

Not verified: Python 3.11 clean install, SerpApi live response or billable API calls, issuer host corroboration by this running application, original/correction raw bytes stored through pinned fetch, scanned-PDF authoritative parsing, alias bridging, complete qualification-scope handling, recorded live judge video.

Environment used for local test: Python 3.13.5.
