# v0.7 bounded, evidence-first end-to-end path

**Status:** synthetic/mocked end-to-end integration passed; **not** an independently
verified live public-notice demo, not a general production solution.

## Run

```bash
python -m pip install -r requirements.txt
python scripts/verify_v07.py
python scripts/demo_v07_offline.py
uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

`GET /health`, `GET /api/capabilities` and `POST /api/check` are implemented.
Without an operator-supplied issuer-attestation manifest **and** a SerpApi key,
`POST /api/check` returns HTTP 503 rather than inventing issuer authority.

## Supported API request

```json
{
  "issuer_id": "configured-issuer-id",
  "issuer_name": "Example Authority",
  "reference_number": "A/2026",
  "supplied_deadline": "2026-10-01",
  "as_of": "2026-10-08T14:00:00+05:30"
}
```

This release does **not** yet parse arbitrary pasted text/screenshots or scanned
PDFs. It accepts a structured notice identity and date; search must find a
strongly matching **original formal notice** and any amendments.

## Explicit live prerequisites

Set `SERPAPI_API_KEY` and `NOTICEDRIFT_ISSUER_ATTESTATIONS` to a local JSON
array controlled and independently checked by the operator (never by API clients).
Its entries contain `issuer_id`, `exact_host`, `verification_evidence_url`,
`verified_at` and `verification_method` (`MANUAL_OFFICIAL_DIRECTORY` or
`MANUAL_CROSS_LINK`). Merely writing a JSON record is not issuer verification.
The operator must verify its provenance before using it in a real check.

## Trust chain

1. Search: bounded plan, fresh provider request, completed status. Search metadata
   is **discovery only**, never governing evidence.
2. Selection: deduplicate URLs, cap sources, and allow official issuer hosts only.
   Potential unverified update URLs may block positive assurance.
3. Capture: bounded source fetch via validated public-IP, pinning and redirects.
4. Extract: only static, completely parsed English text bearing an unambiguous
   reference, issued date, and explicit deadline / extension / cancellation phrase.
5. Ground: source-specific raw byte SHA, text SHA, exact date and relation spans.
6. Admit: exact issuer host attestation + strong family binding; a document is
   immutable, and the event's issued date derives from the captured text.
7. Resolve: one original and a causal, linear sequence of explicitly stated
   `from → to` deadline extensions or full cancellations; every unsupported
   alternative returns `UNRESOLVED`.
8. Output: field values, provenance sources, search manifest, mode label and
   final deterministic verdict.

Synthetic fixtures carry `SYNTHETIC_OFFLINE` mode and use no live API calls.
Even `SUPPORTED_BY_EVIDENCE` is **not** a claim that search indexed every update.

## Unsupported (fail closed)

Post/category-scoped amendments, missing or conflicting issued dates, arbitrary
eligibility text, implicit extensions, formal role ambiguity, nonlinear
supersession/reopening/withdrawal chains, multiple plausible original documents,
unsupported media, partial tables, image-only/scanned PDFs, JS-only documents,
non-English-only corrections, source candidate exhaustion and failed search.

The domain resolver knows richer graph semantics, but this v0.7 adapter chooses
not to synthesize any unsupported event types.

## Release blockers still open

- Independent live SerpApi and actual issuer-domain attestation verification.
- Real-world end-to-end golden family with live/frozen SerpApi evidence.
- Robust candidate ranking / coverage for high-result real searches.
- API-level global rate limiting, end-to-end fetch deadline and resource caps.
- Judge-facing React UI, clean Python 3.11 install, 3-minute demo and submission.
