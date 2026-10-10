# NoticeDrift v0.8.2 — NCA-F real-evidence readiness gate

**Status: PARTIAL.** This is a real-world compatibility checkpoint, NOT a proven end-to-end SerpApi/live-source run.

## Independently checked official source pages (October 9, 2026)

- Original official page: <https://nicf.gov.in/2026/09/14/vacancy-circular-for-two-02-posts-of-teaching-associates/>
- Original official PDF: <https://nicf.gov.in/wp-content/uploads/2026/09/vacancy-circular-two-02-posts-teaching-associates.pdf>
- Official corrigendum webpage: <https://nicf.gov.in/2026/09/17/vacancy-circular-for-two-02-posts-of-teaching-associates-2/>
- Official corrigendum PDF: <https://nicf.gov.in/wp-content/uploads/2026/09/Corrigendum-of-Vacancy-circular-1.pdf>

**Human-reviewed fact:** The original printed deadline is October 1, 2026. The correction's displayed revised deadline is October 26, 2026. The correction also changes essential qualification for one post from *Physiology* to *Psychology*. The automated deadline-only workflow does not verify qualifications.

## Ingestion problems confirmed by reading the real materials

1. **The original PDF's identity differs from the correction PDF's identifier.** Original: `4-22/Estt./Teaching Associates/2026-NCA-F`; corrigendum PDF header: `4-22/Teaching Associate/2026-NCA-F`. The official web corrigendum heading references the former family. This is a notice-family alias problem, **not** a license for fuzzy merging across unrelated notices.
2. **Original has ordinal date typography** (`1st October, 2026`); correction prose says `26th October 2026 instead of 1st October 2026`.
3. **Corrigendum PDF is image-backed/scanned** in the independently reviewed representation. A text-only pipeline must not assume all text is extractable or visually attested. This release deliberately does **not** add OCR that silently makes an authoritative event.
4. **Two distinct changes** are present. The full application must disclose that the qualification correction is not automatically evaluated.
5. **Live production search currently keys off the exact original reference.** Google discovery might omit the different-looking corrected reference, and adequate search calls do not prove update completeness on their own.

## Zero-credit readiness commands

Inside extracted `noticedrift` folder:

```powershell
python scripts/real_case_probe.py
python scripts/live_ncaf_check.py
python -m pytest backend/tests/real_case -q
```

These tools use publisher-reviewed short excerpts and the query planner. Neither contacts SerpApi, fetches official URLs, nor claims captured source bytes.

To independently inspect **operator-downloaded** raw PDFs/HTML, first save the official files locally and then run:

```powershell
python scripts/real_case_probe.py --original-pdf .\original.pdf --corrigendum-pdf .\corrigendum.pdf --corrigendum-html .\corrigendum.html
```

The local-file probes report SHA-256 and parser status, but label their origins as `OPERATOR_SUPPLIED_FILE_UNVERIFIED_NETWORK_ORIGIN`; they never generate governing events.

## Execute actual SerpApi searches — operator-only

**Do not paste API keys into chat, the repository, browser form or command-line flags.** Set the environment variable in your own terminal. The authority manifest must be manually authored/checked by the operator.

`AuthorityAttestation` JSON list schema:

```json
[
  {
    "issuer_id": "ncaf",
    "exact_host": "nicf.gov.in",
    "verification_evidence_url": "https://nicf.gov.in/",
    "verified_at": "REPLACE_WITH_THE_ACTUAL_VERIFICATION_TIMESTAMP_IN_ISO_8601_WITH_TIMEZONE",
    "verification_method": "MANUAL_OFFICIAL_DIRECTORY"
  }
]
```

**The template is intentionally invalid** until the operator independently validates issuer ownership and inserts the actual verification time; it is not an auto-attestation.

```powershell
$env:SERPAPI_API_KEY = "<your private API key>"
python scripts/live_ncaf_check.py --execute --authority-manifest .\issuer-attestations.json --output .\ncaf-live-evidence.json
```

This path can use up to **six** real SerpApi Google searches for the current planned query set. The shared SQLite monthly budget is enabled. The result may be `UNRESOLVED` for legitimate evidence gaps (e.g., scanned correction or an exact-reference mismatch). Never convert `UNRESOLVED` into a confident changed/current verdict.

## Definitive promotion gates (still OPEN)

- [ ] Actual API-keyed SerpApi Google Search returned timestamped, sanitized responses with provider-cache metadata.
- [ ] Exact authorized publisher host validated out-of-band, recorded with correct date.
- [ ] Original notice and corrigendum bytes captured by the pinned-IP fetcher and stored with independently verified hashes.
- [ ] Formal corrigendum source authoring, scope, revision/alias lineage and visibility reliably attested.
- [ ] Qualification-change limitation remains displayed even if the deadline check succeeds.
- [ ] Application returned a justified result with complete search and source coverage, or correctly abstained.
- [ ] Clean Python 3.11 setup and actual judge-browser run verified on user's machine.
- [ ] Under-three-minute judge video records a real locally run check with visible SerpApi discovery.

**Never advertise the reference-case preflight as a successful live SerpApi-powered end-to-end run.**
