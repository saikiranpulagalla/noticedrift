# Clean-install smoke test (Windows PowerShell)

Run this in a fresh clone or extracted release archive. It performs no live
SerpApi request and needs no API key.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts\verify_v085.py
```

In a second PowerShell window, start the judge application:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Then browse to `http://127.0.0.1:8000/` and confirm:

1. The version masthead is `v0.8.5`.
2. The recorded live-search diagnostic says `UNRESOLVED`, `INSUFFICIENT`, and
   `0 captured`.
3. The synthetic section is visibly labeled `SYNTHETIC` and its machine-readable
   entries use `SYNTHETIC`, not `LIVE`.
4. The real-check form remains disabled with no operator configuration.

Stop the server with `Ctrl+C`. Do not add credentials or enable a live check as
part of this smoke test.
