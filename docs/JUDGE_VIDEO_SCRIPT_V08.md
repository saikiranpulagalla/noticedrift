# Judge demonstration — ~1 minute 55 seconds

**0:00–0:13 — show hero.**

> A notice can be genuine and still give the wrong deadline. NoticeDrift looks for a separate correction and checks what governs, rather than trusting the original page alone.

**0:13–0:37 — scroll to the real NCA-F section; click the official corrigendum PDF.**

> Here's a real government example. The original Teaching Associate application deadline was October 1, 2026. A separate official corrigendum changed it to October 26. It also corrected a qualification from Physiology to Psychology for one post.

**0:37–0:49 — return to page and point at the orange disclosure.**

> This is a source-reviewed example, not a claim that my app has verified the live government PDF. The qualification correction is outside the current deadline-only resolver.

**0:49–1:15 — click “Try outdated deadline.”**

> Now I'll show the working pipeline with clearly labelled synthetic data. It runs bounded mock SerpApi discovery, captures two documents, grounds exact quotations, verifies notice identity and uses a deterministic governance-event chain. The old deadline is marked superseded.

**1:15–1:33 — click “Show machine-readable evidence”; scroll to manifest and source traces.**

> The result includes search purposes, source hashes, exact evidence quotations and the governing chain. Six simulated search invocations; no real SerpApi credits were used in this demo.

**1:33–1:49 — click “Try revised deadline.”**

> When I check the revised date, NoticeDrift returns supported by retrieved evidence—never an absolute guarantee that no further correction exists.

**1:49–1:55 — close.**

> The engineering principle is simple: retrieved text isn't authority. Every decisive claim needs identity, trustworthy provenance, and the right event relationship.

## Recording setup

Run `python -m uvicorn app.api.main:app --app-dir backend --host 127.0.0.1 --port 8000`. Open `http://127.0.0.1:8000/`. Keep the whole desktop view visible. If a government PDF doesn't load live during recording, show the provided issuer URL and continue; don't imply the file was ingested by NoticeDrift.
