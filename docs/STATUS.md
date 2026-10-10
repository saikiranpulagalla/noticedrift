# NoticeDrift v0.8.5 — OFFLINE PASS, LIVE GATE OPEN

Release details: `docs/REPAIR_V085.md`. The two independent v0.8.4 audits and inherited tests are installed as regression suites, and missing `fchmod` is simulated in tests. The real API key and government PDF end-to-end have **not** been run, and actual Windows 3.11 installation is still outstanding.

# NoticeDrift v0.8.4 release status (2026-10-09)

**Combined inherited + latest red-team OFFLINE gate PASS; genuine SerpApi/official notice LIVE gate OPEN.**

The v0.8.4 source now rejects silently discarded organic results, malformed pre-search input and oversized incoming API requests; records provider failures as attempted searches; handles evidence-store failures as abstention; compares historical time instants consistently; and requires reviewed canonical issuer / publication-path policy before enabling live mode. Original behavior and both new red-team suites remain tested. `scripts/verify_v084.py` is the authoritative new verifier. These are bounded proof claims for the tested fixtures, not a guarantee of correctness for all real notices.

**Missing evidence:** An authentic keyed SerpApi response that discovers a real, supported corrigendum; public issuer document capture and attestation; Python 3.11 clean runtime confirmation; and final judge video/submission. The NCA-F correction has a scanned PDF, different reference lineage and separate qualification amendment; it is NOT automatically verified by the deadline-only live workflow.

See `docs/REPAIR_V084.md` for the regression and operator migration details. Older version files remain as historical notes.

---

# NoticeDrift v0.8.1 release status (2026-10-08)

**Repaired offline gate; live evidence gate OPEN.**

The v0.8.1 update patches v0.8 independent red-team failures affecting HTML/PDF perceptibility, literal query identity, SQLite credit accounting, live request concurrency, demo-work admission, invalid authority configuration and user-facing live-check access.

- The visible judge UI has a real-check form (`POST /api/check`) that is disabled unless operator-configured. A separate synthetic demo always identifies mock SerpApi responses.
- The source parser downgrades uncertain CSS visibility, low-contrast/tiny PDF glyphs and overlay/background ambiguity. This is **not** general visual rendering verification.
- Provider-credit reservations occur under the elected cache-miss lock. Identical cached requests share one paid attempt. Fresh requests remain real network requests with `no_cache=true`.
- `scripts/verify_v081.py` enforces exact >=95% branch-aware coverage, compilation, complete tests, mock end-to-end demonstration, and 3 full stability runs.
- A bad authority manifest returns an unconfigured application, not a startup exception. No issuer is authorized on the basis of a user-supplied name or URL.

**Unverified / NOT claimed:** actual live SerpApi + official government PDF ingestion; real NCA-F governance result; fully general CSS/PDF rendering; clean external Python 3.11 runtime; deployment; recorded public 3-minute demo. Release requires these checks independently.

See `docs/REPAIR_V081.md` and `docs/JUDGE_V08.md`.
