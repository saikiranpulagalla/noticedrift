# NoticeDrift · v0.8.5 integrity-repaired judge preview

> **The notice was real. Is it still current?**

NoticeDrift finds separately published amendments to notices and resolves the governing actionable values. It is **not a generic search chatbot**. SerpApi supplies bounded search/discovery; fetched source evidence is captured and conservatively admitted before deterministic deadline resolution.

## v0.8.5 — Provider-provenance and platform hardening (offline only)

- SerpApi search returns are invalid if a provider-reported executed query differs from the requested query; malformed/missing organic data cannot silently justify no-update assurance.
- Streaming-bound external SerpApi JSON: 2 MiB limit before decoding. Invalid individual results trigger an incomplete-search error, never false full coverage.
- Reused live API responses now report `provider_calls=0` for **new** calls and `origin_provider_calls` for the original snapshot's attempt count.
- Operator publication-path allowlisting denies encoded dot/step separators, double-encoding, and residual percent ambiguities.
- On Windows/Python 3.11, snapshots use inherited NTFS directory ACLs instead of calling unavailable `os.fchmod`; configure a **private evidence directory**. POSIX still sets 0600.
- Cancelled parsing and snapshot I/O drain the already-started bounded worker rather than leaving unaccounted threads.
- Snapshot archives retain every distinct timestamped capture for replay but refuse new writes after 1024 stored captures or 200 MB of envelopes (defaults). No automatic eviction.
- Offline release gate includes both v0.8.4 audit suites and new provider/retention cross-fix tests. The last reported Windows Python 3.11 verifier passed (521 tests, 95.130537% exact branch-aware coverage, 3/3 stability runs). A complete SerpApi-to-attested-source run remains **NOT VERIFIED**.

Run `python scripts/verify_v085.py`. See `docs/REPAIR_V085.md` for exact contracts and remaining risks.
Windows repair details and the current local-validation limitations are in
`docs/REPAIR_WINDOWS_V085.md`.

## v0.8.4 — Final adversarial repair (offline-verified only)

**What is new:** SerpApi organic-list truncation now fails closed; invalid original URLs are rejected *before* any paid request; request-body sizes are enforced while streaming; historical checks are UTC-invariant; provider failures preserve attempted-call counts; source snapshot I/O failures abstain; HTML/PDF parsing and snapshot storage run outside the server event loop; uncertain low-signal source overflow blocks positive assurance; and operator issuer attestations support canonical issuer names, annual review and explicit publication-path policies. Official search result ranking remains *discovery*, never source authority.

**Important migration for LIVE mode:** issuer-attestation entries must now include `canonical_issuer_name` and `publication_path_prefixes` (operator-reviewed publisher-controlled paths). Without these, the app refuses live readiness. Example manifest and security limitations: `docs/REPAIR_V084.md`.

**Release evidence:** Run `python scripts/verify_v085.py`. It compiles, checks the complete inherited and Round 4/5 adversarial suites with **exact** ≥95% branch-aware coverage, checks the synthetic demo, and repeats tests three times. CI config runs on Python 3.11 and 3.13; this offline environment has independently exercised Python 3.13 only.

**Unverified:** actual SerpApi-authenticated search, real NCA-F corrigendum source-byte capture and automatic governing proof, browser live E2E, clean Python 3.11 outside CI, and production-grade resilience under multi-worker traffic. Do not claim those gates passed.

## Run the judge interface (no API key, no external services)

Python **3.11–3.13**:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/** in your browser. The UI works in unconfigured mode.

### What to click in under three minutes

1. Show the **real NCA-F reference** panel: October 1 → October 26, 2026. Open the official corrigendum PDF or the government page. **This is reference material reviewed from public web sources, NOT an application-captured live SerpApi run.**
2. Mention the qualification correction (Physiology → Psychology for one post). It is shown transparently, **outside the automated deadline-only resolver**.
3. Show **Recorded live-search diagnostic**: six genuine provider attempts, two completions, four bounded timeouts, `INSUFFICIENT` coverage and `UNRESOLVED`. It has **zero** official-source captures.
4. Click **Try synthetic outdated deadline** under *Run the complete workflow* → `SUPERSEDED` from two **synthetic** captured source documents and mock search entries.
5. Click **Show synthetic machine-readable evidence** → exact quotations, source hashes, bounded mock search manifest and decision provenance.
6. Click **Try synthetic revised deadline** → `SUPPORTED_BY_EVIDENCE` (not absolute verified-current).

**Demo honesty:** The code executes the real search planner/executor, source capture, HTML parser, grounding, issuer-host check, governance event builder and resolver. Only the external search transport, issuer domain and document bytes are **fictional**. No live SerpApi searches are made by the offline demo. Its per-search mode is explicitly `SYNTHETIC`.

## Real live-check form (operator-configured only)

The interface now exposes **04 / Check a real notice**. It is disabled unless
`SERPAPI_API_KEY` and `NOTICEDRIFT_ISSUER_ATTESTATIONS` are supplied by the
operator. The issuer name, reference and deadline are entered in the form; the
backend **never** accepts an authority attestation from the user. Live checks
may consume actual SerpApi credits; the monthly SQLite ledger and bounded
API admissions apply. The real NCA-F source panel is separately labeled as
manual reference material and does *not* claim a live SerpApi run.

The parser conservatively abstains on hidden/uncertain HTML, low-contrast or
sub-legible PDF text, opaque backgrounds, unsafe search-identity rewriting, or
incomplete official evidence. Static parsing cannot prove all browser/PDF
rendering conditions; unsupported styles remain `UNRESOLVED`.

## Verify

```powershell
python scripts/verify_v085.py
```

On Windows, the one-command local release check uses an ephemeral
`127.0.0.1` port, checks dependencies, runs the verifier, validates the HTTP
demo contracts, and stops only the server it started:

```powershell
.\scripts\final_release_check.ps1 -Python .\.venv\Scripts\python.exe
```

The verifier compiles the code, runs the full suite with **exact** ≥95% branch-aware coverage, exercises the E2E demo and repeats the complete test suite three times. No live SerpApi credentials are used. Optional browser smoke test was performed separately using Chromium with API-generated fixture responses.

## Routes

| Route | What it does |
|---|---|
| `GET /` | Judge interface, offline-capable |
| `GET /api/reference-case` | Publicly reviewed NCA-F facts with explicit provenance limitations |
| `POST /api/demo/check` | Synthetic E2E check; body `{"supplied_deadline":"2026-10-01"}` |
| `GET /health` | App readiness and config flag |
| `GET /api/capabilities` | Supported scope and live availability |
| `POST /api/check` | **Real live** bounded search check; 503 unless operator config is available |

For operator-only live configuration, see `docs/END_TO_END_V07.md`. In particular, the SerpApi API key and issuer attestations **must not be sent to untrusted clients**. The optional SQLite credit budget is shared across workers if configured correctly.

## Release and submission readiness

See `docs/WINDOWS_RELEASE_VERIFICATION.md` for the actual Windows verification
record and PowerShell commands for a normal Windows environment. The bounded
operator live-check procedure, demo timeline, submission description, checklist,
clean-install plan, and honest limitations are in `docs/submission-readiness/`.
This checkout records a genuine but incomplete SerpApi search diagnostic; it does
not claim a credentialed SerpApi-to-official-source result.

## Supported scope

Explicit structured English notices containing deadlines, deterministic *old → new* extensions and full cancellations; static HTML and supported text PDFs. Unknown identity, ambiguous context, hidden source content, partial PDFs, scoped corrections, unsupported amendment types and incomplete discovery must abstain. The live hero notice is **not yet validated through actual source-byte ingestion with a real SerpApi response**. The real NCA-F page also contains a qualification change outside deadline-only support.

Read `docs/JUDGE_V08.md` for source provenance, reproducibility, and what remains before a production/live demo.

See `docs/REPAIR_V081.md` for the reproduced v0.8 defects, repaired contracts and remaining live-release blockers.

## v0.8.3: real-source discovery improvements (LIVE GATE STILL OPEN)

The `notice_title` input adds one bounded official-host title/corrigendum search without changing the 4 exact-reference core searches or the hard 8-call ceiling. Search hits remain untrusted; different notice numbers are not automatically merged. The live form now uses the same `ncaf` issuer ID, reference and original PDF URL as the operator command, and shows SerpApi search provenance separately from source evidence. For private API-key setup, honest live attempt, and final submission gates, see **[docs/RELEASE_GATE_V083.md](docs/RELEASE_GATE_V083.md)**.

Use `python scripts/verify_v085.py` for the offline release gate. This environment has not completed a real SerpApi/API-keyed end-to-end check.

## New in v0.8.2 — Real-world compatibility/verification kit

`python scripts/real_case_probe.py` checks the **actual published NCA-F wording** as
manually reviewed source excerpts (not source-byte evidence).
`python scripts/live_ncaf_check.py` shows exactly which bounded SerpApi
queries will run, **without making any requests**. With explicit `--execute`,
operator-supplied credentials and a manually attested issuer host, it can
run a genuine source check. No key or issuer manifest is bundled.

See [`docs/REAL_CASE_GATE_V082.md`](docs/REAL_CASE_GATE_V082.md) for source
URLs, the exact reference mismatch, scanned-PDF limitation, operator steps
and promotion gates. The original v0.8.1 safety tests remain unchanged.

Run `python scripts/verify_v082.py` for the strict new offline gate.
**No live SerpApi-powered NCA-F verdict has been verified in this release.**
