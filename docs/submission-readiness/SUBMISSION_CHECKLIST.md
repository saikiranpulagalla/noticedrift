# SerpApi India Hackathon submission checklist

## Project materials

- [ ] Select **Knowledge & Public Interest** (or consciously choose another track).
- [ ] Optionally choose and add a repository license. This checkout currently
  has no `LICENSE` file; do not guess the owner’s licensing intent. Its absence
  is not a submission blocker.
- [ ] Publish a public GitHub repository only after verifying it excludes `.env`,
  keys, quota databases, private evidence, caches, virtual environments, audit
  logs, and personal filesystem paths.
- [ ] Include source, `requirements.txt`, tests, `scripts/verify_v085.py`, README,
  repair documentation, `docs/WINDOWS_RELEASE_VERIFICATION.md`, and this folder.
- [ ] Run the clean-install smoke plan in `CLEAN_INSTALL_SMOKE_TEST.md`.
- [ ] Follow `PUBLISHING.md` after verifier success and explicit publication approval.
- [ ] Re-run the release verifier after final packaging/content changes and record
  its actual result; preserve the existing Windows gate record separately.

## Submission form

- [ ] Project name: **NoticeDrift**.
- [ ] Paste the appropriate fields from `FINAL_SUBMISSION_CONTENT.md`.
- [ ] Provide the public repository URL.
- [ ] Explain material SerpApi usage using `PROJECT_DESCRIPTION.md`.
- [ ] Use `DISCLOSURES.md` to state pre-existing work and AI-tool assistance
  accurately; replace placeholders with the participant’s actual facts.
- [ ] Supply participant details privately; do not commit them.
- [ ] Accept rules and terms only after reviewing them.

## Video

- [ ] Record a local-running screen demonstration under three minutes.
- [ ] Follow `DEMO_PLAN.md`: distinguish manual reference material, the live
  diagnostic, and the synthetic workflow.
- [ ] State that the live diagnostic is `UNRESOLVED` / `INSUFFICIENT` with zero
  official-source captures; do not imply source authentication.
- [ ] Upload to an accessible host and test the final link in an incognito/private window.

## Final gates

- [ ] Preserve the verified Windows Python 3.11 baseline: 521 tests,
  95.130537% exact branch-aware coverage, 3/3 stability, release verifier PASS.
- [ ] Re-run it after final submission changes in a normal supported environment.
- [ ] Keep the live gate explicitly `LIVE_SERPAPI_NOT_VERIFIED` until an
  authorized provider-to-attested-source run completes.
- [ ] Submit before 2026-10-10 23:59 IST.
