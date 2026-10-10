# Public-repository publishing procedure (Windows PowerShell)

This checkout has no `.git` metadata and no chosen license. Review every staged
file before committing. A license is optional for this submission; if the owner
wants an open-source license, choose it deliberately rather than guessing.
Do not publish until the clean-install verifier has passed after final changes.

## Preflight

```powershell
Set-Location 'C:\Users\saiki\Downloads\noticedrift'

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\verify_v085.py
```

Review the exclusions before initializing Git. The project `.gitignore` must
keep `.env`, `.venv`, `.noticedrift-evidence`, `*.sqlite3*`, caches, logs, and
local test directories out of the public repository.

## Initialize and inspect (only after preflight passes)

```powershell
git init
git branch -M main
git add .
git status --short
git diff --cached --check
git diff --cached -- . ':!docs/submission-readiness'
```

Before the commit, inspect staged names carefully. Remove any unexpected
private file from the index with `git restore --staged -- <path>`; do not delete
the original file merely to prepare the repository.

## Commit and publish (requires explicit owner approval)

```powershell
git commit -m "Prepare NoticeDrift v0.8.5 hackathon submission"
git remote add origin 'https://github.com/OWNER/REPOSITORY.git'
git remote -v
git push -u origin main
```

After publishing, inspect the GitHub file list while signed out or in a private
browser. Confirm that no credentials, evidence directory, SQLite ledger,
personal local paths, or private reports are present.
