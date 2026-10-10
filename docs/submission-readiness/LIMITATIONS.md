# Honest implementation limits

## Implemented now

- Bounded SerpApi Google-search adapter, query-provenance checks, per-query
  status/timing diagnostics, and quota accounting.
- Operator-attested exact-host/publication-path enforcement, pinned-IP safe
  fetching, source byte/text hashing, bounded storage, static HTML/text-PDF
  parsing, exact quotation grounding, and deterministic deadline
  extension/full-cancellation resolution.
- Explicit synthetic end-to-end judge demo with fictional sources, and a
  separate sanitized record of the latest genuine provider-search diagnostic.
- Windows Python 3.11 release verifier previously reported as passed: 521
  tests, 95.130537% exact branch-aware coverage, and 3/3 stability runs.

## Live evidence status

- A genuine SerpApi provider search was run: two attempts completed and four
  reached the 15-second total-attempt deadline.
- That run is `UNRESOLVED` with `INSUFFICIENT` coverage and zero
  official-source captures. It does not prove an original, corrigendum, or
  governing deadline.
- A complete provider-to-attested-source capture and governing live verdict
  remain unverified.

## Deliberately unsupported / fail closed

- Scanned/image-only PDFs and OCR-derived authority claims.
- Fuzzy merging of different notice references.
- General HTML/CSS/PDF visual-rendering proof.
- Ambiguous, scoped, conflicting, withdrawn, or nonlinear amendment chains.
- Proof that no unindexed later amendment exists.
