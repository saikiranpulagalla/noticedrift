# Windows release verification — v0.8.5

## Current status

| Gate | State | Evidence |
|---|---|---|
| Python 3.11.9 full v0.8.5 verifier | TESTED AND PASSED | 521 tests passed; full release verifier PASS |
| Exact branch coverage | TESTED AND PASSED | 95.130537% exact branch-aware coverage |
| Three stability runs | TESTED AND PASSED | 3/3 passed |
| Windows asyncio regressions | TESTED AND PASSED | Included in the reported full verifier result |
| Codex AppContainer asyncio | BLOCKED BY ENVIRONMENT | The sandbox still stalls on plain `asyncio.run(asyncio.sleep(0))`, even without NoticeDrift's guard; this is not the normal Windows result |
| Python 3.13 | NOT TESTED | Not available in this session |
| Hosted Windows CI | NOT TESTED | Workflow is configured but no Git repository/Actions run is accessible from this checkout |

## Required independent Windows PowerShell verification

Run this from a normal Windows checkout, not an AppContainer-restricted shell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts\verify_v085.py
```

Then repeat with any available supported interpreters:

```powershell
py -3.12 -m venv .venv312
.\.venv312\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\verify_v085.py
```

The reported Python 3.11 result supports `OFFLINE_RELEASE_PASS` for the tested
pre-submission state. Re-run the command after final packaging/content changes
and record its exact output before publishing a release archive.
