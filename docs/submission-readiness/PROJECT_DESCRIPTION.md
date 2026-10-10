# NoticeDrift — submission copy

## Project description

**NoticeDrift answers a deceptively important question: a notice may be
authentic, but is it still current?** Institutions often publish deadline
extensions, corrigenda, or cancellations as separate documents. NoticeDrift
uses bounded SerpApi discovery to find those candidates, admits only
operator-attested official sources, preserves hashes and exact quotations, and
uses a deterministic event chain to decide whether a submitted deadline is
superseded, supported by retrieved evidence, or unresolved.

It is deliberately conservative: search snippets never govern a result. An
ambiguous, untrusted, incomplete, scanned, or partially visible source yields
`UNRESOLVED` rather than a confident guess.

## Recommended track

**Knowledge & Public Interest.** NoticeDrift helps applicants and citizens
interpret time-sensitive institutional notices while exposing the limits of the
underlying evidence.

## Material SerpApi usage

SerpApi is a functional dependency, not a decorative lookup. The live workflow
uses bounded Google searches through SerpApi to discover separately published
originals, corrigenda, extensions, cancellations, and official-host candidates
from a structured notice reference. Provider query provenance, status,
per-attempt timing, size limits, result integrity, credit accounting, and the
complete search manifest control whether source review may proceed. Search hits
remain discovery hints: the application independently fetches only
operator-attested official hosts and verifies source bytes before evidence can
govern a verdict.

## Honest live-validation disclosure

A genuine six-attempt SerpApi search diagnostic has been recorded: two provider
attempts completed and four reached the 15-second total-attempt deadline. The
result is `UNRESOLVED` with `INSUFFICIENT` coverage and **zero official-source
captures**. Do not describe this as a verified notice result or an
end-to-end source verification. The repository also includes an explicitly
labeled synthetic workflow for demonstrating the complete evidence pipeline.
