# 2:30 judge-demo plan

Use only a local server at `http://127.0.0.1:8000/`. Keep private environment
variables, the credit ledger, and any private evidence directory out of frame.

| Time | Screen/action | Narration and proof point |
|---|---|---|
| 0:00–0:18 | Landing page and headline | “A notice can be authentic but obsolete when its issuer publishes a separate corrigendum. NoticeDrift finds candidates, admits only authenticated official evidence, and abstains when that chain is incomplete.” |
| 0:18–0:35 | **01 / An actual government correction** | “This is manually reviewed public context, not an application-captured result.” Point to the explicit label and source caption. |
| 0:35–1:05 | **02 / Recorded live-search diagnostic** | “This is the honest live SerpApi result: six real provider attempts; two completed in 1.547 and 0.937 seconds; four hit the 15-second bound. Coverage is insufficient, so the verdict is `UNRESOLVED`.” Point to “0 captured”: no official page or PDF was fetched, hashed, or authenticated. |
| 1:05–1:18 | Same diagnostic | “This is a safety property: partial discovery never becomes a claimed deadline change or a claim that no change exists.” |
| 1:18–1:55 | **03 / Run the complete workflow**; click **Try synthetic outdated deadline** | “This section is explicitly `SYNTHETIC`. It runs the real bounded planner, source-capture, hashing, parsing, grounding, and deterministic resolver against fictional mock search entries and source bytes. It is not a live SerpApi response.” Show `SUPERSEDED`. |
| 1:55–2:12 | Click **Show synthetic machine-readable evidence** | Show `SYNTHETIC_OFFLINE`, per-entry `SYNTHETIC` modes, synthetic hashes, exact quotations, and the event chain. |
| 2:12–2:25 | Click **Try synthetic revised deadline** | “With the revised input, the resolver says `SUPPORTED_BY_EVIDENCE`, not ‘verified forever.’” |
| 2:25–2:30 | **04 / Check a real notice** | “Live mode requires an operator key and independently reviewed issuer-host/path policy; browser input cannot supply authority.” |

Before recording: run the offline demo once, verify no key/path is visible, and
test the final video link in an incognito/private browser.
