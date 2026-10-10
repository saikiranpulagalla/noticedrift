# NoticeDrift v0.8.4 — Final dual-audit repair

## Scope and status

This is the repair of the two v0.8.3 source audits (10 and 7 probes), plus regression tests for interactions between the fixes. Unlike earlier release claims, only the **offline/mock boundary** is verified here. No real SerpApi API key, authenticated provider call, or real NCA-F binary source was used.

## Changes and why they don't weaken safety

| Risk | Repair | Fail-safe behavior |
|---|---|---|
| Successful provider payload silently drops result 101+ | Adapter rejects >100 organic results with `PROVIDER_RESULT_TRUNCATED`, hashed error manifest | No positive conclusion from unseen results |
| Bad original URL spends 6 provider requests before failing | Pydantic validates URL syntax/length using shared safe-target policy | HTTP 422; zero billable dispatches |
| Source order/noise can swamp limited extraction | Preserve original provider order under limit; rank exact-identity / official amendment hints only on overflow | Empty/overloaded weak set abstains, and overflow blocks positive assurance |
| Incorrect timezone-based same-day reasoning | UTC-normalize requested instant before date-only issuance gating | Equal instants receive equal semantic verdicts |
| Unexpected third provider exception loses usage metadata | Adapter catches exceptional provider attempt, emits `PROVIDER_EXCEPTION` and keeps attempts/manifests | Search coverage cannot become adequate |
| Snapshot write failure escapes as HTTP 500 | Convert permitted persistence failures to `EVIDENCE_PERSISTENCE_FAILED` and preserve search count | `UNRESOLVED` |
| Expensive PDF/text parsing blocks asyncio event loop | Fetch, parse and snapshot storage are offloaded from event loop | ASGI remains responsive; actual already-started threads are not preemptible |
| Any hostname path may be misclassified issuer-authored | Operator canonical name, fresh attestation, approved publication path prefixes, denial of known user paths | Network live mode abstains until operator config complete |
| Oversized JSON POST admitted | ASGI middleware rejects Content-Length or actual streamed body above 64 KiB | HTTP 413, no parse/search |
| Responsive CSS ignored or taints unrelated content | Visibility rule matched against selected issuer-body subtree; conditional matching evidence downgrades | Abstains on ambiguous visible content |

## Operator live-mode manifest — migration from v0.8.3

The operator must **independently** validate the issuer identity, official publishing channels and the URL prefixes that belong to issuer-controlled notices; searching Google or finding a `.gov.in` hostname is **not** evidence of document authorship.

A STRUCTURE-ONLY example (not a verified authority record):

```json
[
  {
    "issuer_id": "ncaf",
    "canonical_issuer_name": "National Communications Academy Finance",
    "exact_host": "nicf.gov.in",
    "publication_path_prefixes": [
      "/2026/09/14",
      "/2026/09/17",
      "/wp-content/uploads/2026/09"
    ],
    "verification_evidence_url": "https://nicf.gov.in/",
    "verified_at": "REPLACE_WITH_ACTUAL_VERIFICATION_TIME_ISO8601_TZ",
    "verification_method": "MANUAL_OFFICIAL_DIRECTORY"
  }
]
```

Do **not** copy the illustrative paths without checking the actual issuer's publication/authorship policy. This prefix set is an operator *declaration*, not external authentication, and cannot rule out every user-contributed document at a permitted path. To remain conservative, user-upload patterns are denied even on attested hosts; unsupported authorship/scope abstains. The current parser handles only explicit English deadline changes and full cancellations, **not scanned PDF authority**, eligibility revisions, or fully general browser visibility.

## Reproduction

From a clean extraction:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\verify_v084.py
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

When no SerpApi key or complete operator manifest is supplied, `/api/check` remains unavailable; `/api/demo/check` uses **SYNTHETIC** search evidence only.

## Remaining release blockers

1. Real keyed SerpApi search and genuine issuer document snapshot verification not available in this runtime.
2. NCA-F original/corrigendum mismatched references and image-only PDF cannot yield a verified automatic `SUPERSEDED` verdict yet.
3. Clean independent Python 3.11 reproduction and full browser live path not completed here.
4. Search-index completeness, general layout/perceptibility, publisher-host path authorship, and worker cancellation remain conservative limitations; a verified public endpoint needs additional operating controls.
5. Public repository, <=3 minute video and official submission remain user-owned actions.
