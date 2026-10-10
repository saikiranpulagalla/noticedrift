# v0.8 — Judge Preview and Evidence Contract

## Provenance boundary

**Real-world reference, manual web review:** The National Communications Academy–Finance published a vacancy circular (two Teaching Associate posts) and a corrigendum dated September 17, 2026. The issuer webpage and first English page of its attached PDF state the deadline is **October 26, 2026 instead of October 1, 2026**. The PDF separately corrects essential qualifications for one post from *Physiology* to *Psychology*. The application displays these verified-from-public-view facts only as **contextual information**.

Primary sources:

- https://nicf.gov.in/2026/09/14/vacancy-circular-for-two-02-posts-of-teaching-associates/
- https://nicf.gov.in/2026/09/17/vacancy-circular-for-two-02-posts-of-teaching-associates-2/
- https://nicf.gov.in/wp-content/uploads/2026/09/Corrigendum-of-Vacancy-circular-1.pdf

The application's real-reference endpoint discloses:

```json
{
  "provenance_level": "PUBLIC_WEB_REVIEWED_TRANSCRIPTION",
  "application_snapshot_verified": false,
  "serpapi_run_executed": false,
  "automated_governance_verdict": null
}
```

**Do not** change these flags to `true` until a full live SerpApi → original PDF → correction PDF snapshot → event → resolver run has succeeded with evidence hashes from actual fetched bytes. The official PDF has a qualification correction and bilingual/scan-like visual layout, which the deadline-only extractor does not automatically interpret. The issuer's original PDF and correction PDF also have differing reference formats; binding must be validated rather than assumed.

## Synthetic demonstration

The `POST /api/demo/check` path invokes all production domain, query-planning, HTML-ingestion and provenance logic but swaps only the external SerpApi service and issuer pages for well-defined mock classes. The fixture uses `issuer.example`, `Reference: A/2026`, and dates October 1 → October 26. It is **not copied or attributed to the government**. Both mock results carry `SearchMode.SYNTHETIC`; without an explicit simulated executor flag these results cannot contribute ADEQUATE live search coverage.

- Old input deadline → `SUPERSEDED`, new governing value October 26.
- New input deadline → `SUPPORTED_BY_EVIDENCE`.
- Provider calls in the response are **mock invocations**, not paid API usage.
- The UI labels the simulation and the real-reference section distinctly and links the real sources directly.

## Reproduction

```powershell
python -m pip install -r requirements.txt
python scripts/verify_v08.py
python -m uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In a separate terminal open `http://127.0.0.1:8000/`, click the two deadline examples, and inspect raw evidence.

**Browser test status:** Chromium desktop and 390px mobile layouts rendered, buttons worked, no JS runtime exceptions. Browser navigation to a real localhost server was blocked by the hosted verification environment, so browser smoke used actual API-generated JSON as an intercepted page-local fixture. The API itself passed independent ASGI contract tests. This is not a claim of a full live network browser test.

## Not completed / avoid overclaims

- **No live SerpApi credential used** in this release; user must supply their own key for configured live checks.
- **No live official-source byte ingestion proof** or captured hash manifest for the NCA-F real case.
- **No automated verification of essential-qualification corrections.**
- **No Python 3.11 clean install locally verified** (local runtime: 3.13.5; CI configured for 3.11 and 3.13).
- Not a production-ready, comprehensive job-recruitment checker, a legal notification verifier, or a proof that no later unindexed amendment exists.
- Keep `UNRESOLVED` for unsupported or contradictory documents; never infer governing truth from ranking or snippets.
