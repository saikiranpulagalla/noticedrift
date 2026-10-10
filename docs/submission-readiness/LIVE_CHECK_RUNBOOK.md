# Bounded genuine SerpApi live-check runbook

This procedure is intentionally operator-controlled. It does not provide an
authority manifest or source bytes, and it must not be used until an operator
has independently reviewed the issuer identity, exact host, and permitted
publication paths.

## What the implementation does

`POST /api/check` uses `SerpApiClient` against `https://serpapi.com/search.json`
with the Google engine, `gl=in`, `hl=en`, and fresh `no_cache=true` requests.
The planner emits four literal-reference core searches (identity, corrigendum,
extension, cancellation) plus up to two bounded official-host/title expansions.
The hard ceiling is eight calls; the current NCA-F dry run produces six.

The adapter records sanitized provider metadata, query identity, provider status,
result count, a response SHA-256 where available, and a controlled per-query
error code in the search manifest. It rejects malformed,
rewritten, truncated, cached, oversized, or incomplete provider evidence. Results
are discovery hints only. The workflow fetches only operator-attested exact hosts
through the pinned-IP source fetcher, captures bytes in a SHA-256 envelope,
parses supported static HTML/text PDFs, grounds exact quotations, then resolves a
strict deadline event chain. Unsupported evidence returns `UNRESOLVED`.

## Preflight: no credits, no network

```powershell
python scripts\live_ncaf_check.py
```

This prints planned queries, the maximum call count, and NCA-F limitations. It
does not use a key or make a request. Do not use NCA-F as the final live proof
unless its differing references and scanned/qualification material are supported
by a separately approved scope.

## Operator preparation

1. Select an issuer with an official, static, text-extractable original and an
   explicit `from … to …` correction carrying the same exact notice reference.
2. Independently review the issuer identity and official publication route.
3. Create a local, untracked authority-manifest JSON file containing only the
   reviewed issuer ID, canonical issuer name, exact host, verification evidence
   URL, aware verification timestamp, verification method, and approved
   publication-path prefixes. Never accept this data from the browser.
4. Choose a private evidence directory and a new, unused output path. Do not
   place either in the repository.
5. Set a conservative monthly credit limit and the private key only in the
   current PowerShell session.

## Explicit execution: may spend credits

The supplied script is NCA-F-specific; use it only after accepting the listed
limitations. It refuses execution without `--execute`, a key, and a manifest.

```powershell
$secureKey = Read-Host -Prompt 'SerpApi key' -AsSecureString
$env:SERPAPI_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password
Remove-Variable secureKey

$env:NOTICEDRIFT_MONTHLY_SEARCH_LIMIT = '8'
python scripts\live_ncaf_check.py --execute `
  --authority-manifest 'C:\private\noticedrift-authority.json' `
  --evidence-dir 'C:\private\noticedrift-evidence' `
  --output 'C:\private\noticedrift-live-result.json'
```

Before recording the screen, inspect the output: execution mode, `provider_calls`,
search entries, source URLs, raw/text SHA-256 values, parser statuses, grounded
quotes, final verdict, and warnings. Redact paths and any non-public data before
sharing. A provider error, unsupported source, or `UNRESOLVED` is a valid honest
outcome; do not retry indiscriminately or claim completion.

## Live gate

A genuine six-attempt provider search has been recorded: two completed and four
reached the bounded total-attempt deadline. It returned `INSUFFICIENT` coverage,
`UNRESOLVED`, and zero official-source captures. Therefore the complete live
gate remains **LIVE_SERPAPI_NOT_VERIFIED**. Do not use the recorded search
diagnostic as an official-source capture or governing verdict.
