# v0.6 safe source ingestion — implemented contract

Status: **offline test gate implemented**; live domain ownership, real SerpApi-to-source end-to-end, and judge application remain **UNVERIFIED / NOT IMPLEMENTED**.

## Trust pipeline

1. A search-result URL is merely a **candidate**, never authority.
2. `SafeSourceFetcher` validates URL and **every redirect**, performs public DNS validation, and pins the actual socket connection to a checked numeric IP. HTTPS certificate validation uses the original hostname (not the numeric IP). It never follows ambient proxy settings, sends cookies, or performs JavaScript.
3. The bounded snapshot records source URL, final URL, redirect chain, content type, captured-at and exact raw-body SHA-256. Limit 8 MB, three redirects, two IP attempts each, no other ports than HTTP 80 / HTTPS 443, HTTP GET only. Unsupported content encodings and types fail closed.
4. `parse_snapshot` supports static HTML, UTF-8 text and text-bearing PDFs. Flattened HTML/PDF tables, visually significant images, embedded content, truncated text and multi-page over-limit documents are `PARTIAL`; scanned, encrypted and empty documents are `UNSUPPORTED`; corrupt PDFs are `FAILED`.
5. `ground_exact_quote` binds a unique exact quotation to **both** raw-source SHA and parsed-text SHA and, where available, a PDF page number. It never trusts a search snippet as a source quotation.
6. `admit_document` validates that grounded typed field value actually matches its raw quoted value. It cannot grant `ISSUER_PRIMARY` from a `.gov.in` suffix or search rank. Exact issuer/host entries are curated by the operator with an independently checked official directory/cross-link reference. This is a **manually supplied attestation**, not live cryptographic domain verification.
7. A partially parsed formal correction automatically carries `POTENTIAL_GOVERNING` impact. Nothing here fabricates a `GovernanceEvent`; **relation, scope, chronology and governing-event admission remain the next end-to-end integration boundary**.
8. `SnapshotStore` uses atomic replace and an envelope SHA-256 covering **both raw bytes and source metadata**, verifies it on each read and rejects unsafe keys, corrupted data and oversized envelopes. It is *tamper-evident relative to an already-held digest*, not an authenticated signature against an adversary who controls the digest and storage.

## Reproducible offline proof

```bash
python scripts/demo_v06_offline.py
python scripts/verify_v06.py
```

Both are designed to use zero live SerpApi requests. The first uses explicitly synthetic issuer data, not a real official notice. Public source URLs are not assumed reachable or authentic from successful mock tests.

## Unsupported

Scanned/OCR PDFs, complex tables, JS-only applications, embedded frames, uncommon encodings and non-HTTP formats. Unverified or partially parsed potentially governing documents must be shown as unresolved in the eventual end-to-end application, not silently discarded.

## Remaining release blockers

* An operator must independently verify every real issuer-to-host attestation and document its reference evidence.
* Candidate notice-family binding, grounded **relation** spans, target-event lineage, applicable scope and issued/effective dates are not yet fed automatically into the end-to-end resolver.
* Full evidence coverage must combine search completion **and source parse status**, not merely successful API calls.
* Live SerpApi queries, live pinned TLS fetches against official hosts, Python 3.11 clean environment, frontend, local demo and submission are still unverified.
* Source loading is synchronous; bounded per-socket timeout does not impose a strict end-to-end time budget over DNS or multiple redirects. Production integration needs a whole-analysis deadline and concurrency/rate caps.
