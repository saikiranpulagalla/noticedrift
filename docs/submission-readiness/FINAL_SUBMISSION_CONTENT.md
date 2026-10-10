# NoticeDrift — ready-to-paste submission content

## Project title

NoticeDrift

## Recommended track

Knowledge & Public Interest

## Short description

NoticeDrift helps people determine whether an authentic institutional notice is
still current. It uses bounded SerpApi discovery to find possible corrigenda,
extensions, and cancellations, then admits only verified official-source
evidence into a deterministic, fail-closed decision.

## Full description

Official notices often remain online after a later corrigendum changes an
application deadline, qualification, or status. NoticeDrift addresses the gap
between “this document is authentic” and “this value still governs.” It plans
bounded searches from a structured notice identity, records provider provenance,
and treats search results only as discovery leads. It then permits only
operator-attested issuer hosts and publication paths, captures source bytes with
SHA-256 evidence envelopes, parses supported static documents, grounds exact
quotations, and evaluates a deterministic amendment timeline.

The system deliberately abstains when discovery or source evidence is
incomplete. Its current recorded genuine SerpApi search diagnostic contains six
attempts: two completed and four reached the 15-second total-attempt deadline.
Because coverage was insufficient and no official source was captured, the
recorded result is `UNRESOLVED`, not a claimed verified deadline. The local demo
also includes a fully labeled `SYNTHETIC` end-to-end deadline-correction example
using mocked SerpApi responses and fictional evidence.

## Problem and solution

**Problem:** applicants and citizens can rely on an original notice while a
separate official corrigendum, extension, or cancellation changes the governing
value.

**Solution:** NoticeDrift separates discovery from evidence. SerpApi finds
candidate documents under a bounded budget; official-source bytes, exact
quotation grounding, and a deterministic event chain are required before a
deadline can be supported or superseded. Any uncertain state fails closed to
`UNRESOLVED`.

## Meaningful SerpApi integration

SerpApi is a functional dependency, not a cosmetic API call. The live adapter
uses bounded Google searches for notice identity, corrigendum, extension,
cancellation, and approved official-host discovery. It captures requested and
provider-executed query provenance, status, per-attempt timing, result integrity,
size limits, cache state, and credit accounting. These conditions determine
whether source review can proceed; snippets never determine a verdict.

## Technical architecture

- FastAPI local judge interface and strict JSON request models.
- Bounded SerpApi client and planner with query-provenance verification.
- Shared SQLite credit ledger and conservative request admission limits.
- Exact issuer-host and publication-path authority policies.
- SSRF-resistant pinned-IP source fetcher, bounded snapshot storage, SHA-256
  evidence envelopes, static HTML/text-PDF parsing, and exact grounding.
- Deterministic governance-event resolver with `SUPERSEDED`,
  `SUPPORTED_BY_EVIDENCE`, or fail-closed `UNRESOLVED` outcomes.
- Clearly separated manual reference material, archived real search diagnostics,
  and synthetic demo evidence.

## Challenges and accomplishments

The difficult part was preserving truth under partial information: search
providers can time out, source documents can be unsupported, and a search hit
is not source authority. NoticeDrift records that limitation instead of turning
partial discovery into a confident answer. The project has a complete synthetic
demonstration, a recorded genuine-provider diagnostic with transparent failure
states, Windows-focused persistence and test-isolation repairs, and a
PowerShell release checker that uses a private ephemeral loopback port and
cleans up only its own server process.

## AI-tool disclosure

OpenAI Codex was used for AI-assisted coding, testing support, and
documentation. The participant reviewed the code, security constraints, tests,
and all submission claims. AI-generated content is not represented as
independently verified live evidence.

## Pre-existing-work disclosure

NoticeDrift includes pre-existing application, test, and documentation work
created before final hackathon-submission preparation. This submission packages
that work together with release verification, Windows compatibility repairs,
synthetic/live evidence labeling, SerpApi diagnostic observability, and
submission materials. Amend this statement if the hackathon rules require a
more specific timeline or component inventory.

## Known limitations

- The recorded genuine SerpApi search has two completed attempts and four
  timeouts; coverage is `INSUFFICIENT` and the result is `UNRESOLVED`.
- No official-source bytes, hashes, or governing deadline were captured in that
  run.
- Scanned/image-only PDFs, fuzzy notice-family matching, and unsupported or
  ambiguous amendment chains deliberately fail closed.
- Search cannot prove that no unindexed later notice exists.

## Links

- GitHub: `https://github.com/OWNER/noticedrift`
- Demo video: `https://VIDEO-HOST/NOTICE-DRIFT-DEMO`
