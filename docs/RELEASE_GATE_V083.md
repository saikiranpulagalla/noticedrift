# NoticeDrift v0.8.3: bounded official-source discovery

Status: **OFFLINE GATE ONLY**. The live SerpApi / issuer-authority / official-source-byte gate has **not** been passed in this environment.

## Specific real-case improvement

- The NCA-F original notice uses `4-22/Estt./Teaching Associates/2026-NCA-F` while its correction PDF uses another numbering format. No automatic alias is inferred.
- Four reference-exact CORE searches stay unchanged. A new optional `notice_title` is a **search-only hint**: it substitutes a `site:nicf.gov.in "Teaching Associates" corrigendum` discovery query for a weaker fallback, within the same 6-query plan / 8-call absolute cap.
- `notice_title` **cannot** authorize a host, override reference identity, or decide a verdict. A discovered corrigendum with a mismatched reference or scanned/ambiguous content must remain `UNRESOLVED` until independent evidence validates the relationship.
- The live UI presets now agree with the CLI/authority-manifest issuer ID, original notice reference, and real source URL. Live execution remains disabled without operator setup.
- The live UI displays the SerpApi **search manifest** (query purpose, status, provider/cache mode, result count) separately from *governing source evidence*. Search snippets do not become governance events.

## Published source references for human inspection

- Original issuer notice page: https://nicf.gov.in/2026/09/14/vacancy-circular-for-two-02-posts-of-teaching-associates/
- Original PDF: https://nicf.gov.in/wp-content/uploads/2026/09/vacancy-circular-two-02-posts-teaching-associates.pdf
- Correction page: https://nicf.gov.in/2026/09/17/vacancy-circular-for-two-02-posts-of-teaching-associates-2/
- Correction PDF: https://nicf.gov.in/wp-content/uploads/2026/09/Corrigendum-of-Vacancy-circular-1.pdf

The published correction describes a deadline change **October 1 → October 26, 2026** and a separate qualification correction (**Physiology → Psychology** for one post). The automated resolver is deadline-only; it must never suggest it verified the qualification correction.

## Clean user-machine run (PowerShell)

From this ZIP's `noticedrift` folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\verify_v083.py
.\.venv\Scripts\python.exe scripts\live_ncaf_check.py
```

The final command is a **dry run**: zero network/API calls, no key, no false live verdict.

For a genuine live attempt, open and independently verify the issuer's official site and trusted institution listing. Create `issuer-attestations.json` yourself, with a **truthful** verification timestamp, not a pre-filled fabricated one:

```json
[
  {
    "issuer_id": "ncaf",
    "exact_host": "nicf.gov.in",
    "verification_evidence_url": "https://nicf.gov.in/",
    "verified_at": "REPLACE_WITH_REAL_CHECK_TIME_IN_ISO_8601_WITH_TIMEZONE",
    "verification_method": "MANUAL_OFFICIAL_DIRECTORY"
  }
]
```

Keep the SerpApi key out of the repository and chat. Enter it privately in your PowerShell process:

```powershell
$secret = Read-Host "SerpApi key" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try { $env:SERPAPI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
.\.venv\Scripts\python.exe scripts\live_ncaf_check.py --execute --authority-manifest .\issuer-attestations.json --output .\ncaf-live-evidence.json
```

**Check the output before claiming success.** It may report `UNRESOLVED`, unavailable source, or rejected authority even when a real SerpApi query succeeded. A correct abstention is preferable to a misleading demo.

The `ncaf-live-evidence.json` file may contain source URLs, search references and analysis metadata; inspect/redact it before publishing. **Never publish API keys, signed URLs, private information or unreviewed source content.** The output command uses exclusive creation and will refuse to overwrite an existing file; use another filename for a later attempt.

To run the browser demo locally:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Opening this interface with no live credentials is still useful as an honestly labeled **synthetic demonstration**, but it is not proof of live SerpApi functionality.

## Remaining MUST-PASS gates

- [ ] At least one SerpApi API-keyed, provider-response-backed live query with actual request metadata and non-cached classification.
- [ ] Human-corroborated issuer authority manifest with truthful timestamp.
- [ ] Official source bytes downloaded on user machine through checked transport and hashed; verify the actual original and correction source identity/lineage.
- [ ] Honest outcome: valid `SUPERSEDED` proof **or** `UNRESOLVED` with explicit missing evidence. Never promote scanned/ambiguous evidence to governing truth.
- [ ] Clean Python 3.11 full verifier and browser clickthrough on judge machine.
- [ ] Public GitHub repo; demo recording **under 3 minutes** showing locally running features; submission completed by official deadline.

The published hackathon rules require **material SerpApi integration**, a public repository, and a shareable <3-minute video. A synthetic-only demonstration does not establish the live integration claim.
