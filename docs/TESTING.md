# Testing and required gates

Run `python scripts/verify_v051.py` for compilation, >=95% branch-aware coverage of domain+search, plus three consecutive full-suite runs.

Adversarial cases directly test: weak and scoped withdrawal, withdrawal-of-withdrawal, parser trust, authority classes and document roles, same-time lineage, partial cancellation, source provenance, duplicate IDs, effective dates, canonical values, Unicode identity, insecure URLs, provider cache status, path traversal, tampered replay, cache corruption, malformed SerpApi payloads, query injection, query limits, cache single-flight with 25 requests, pinned search params and input cardinality.

**Measured coverage is a test metric, not a guarantee of real-world search recall.** The core release contract still requires 0 known P0/P1 errors and clean live smoke, fresh Python 3.11 setup, issuer/source ingestion and judge demo before a claim of full release is warranted.

## Independent v0.5.2 audit regressions
- `backend/tests/adversarial/test_independent_new_failure_hunt.py`: 15 independently authored tests (round 2).
- `backend/tests/adversarial/test_round3_novel.py`: 12 independently authored tests (round 3).
- `backend/tests/adversarial/test_v052_interaction_regressions.py`: extra cross-fix regressions.
- In two older unit tests, an identity-only search was expected to yield `ADEQUATE`; this assertion was intentionally corrected to `PARTIAL`, because successful search execution is not completeness of amendment discovery.
- All tests are offline; automatic network denial is enforced by conftest.
