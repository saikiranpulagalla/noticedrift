# v0.8.5 — Integrated repair of two independent v0.8.4 audits

## Safety contracts and implementation

1. **Search identity:** When SerpApi supplies `search_parameters.q`, the adapter compares its normalized whitespace representation to the actually requested query. A substantive mismatch returns `EXECUTED_QUERY_MISMATCH` with status `ERROR`. Missing optional echoes are not fabricated as matches. This comparison deliberately avoids case folding, as quoted notice references may be significant.
2. **Response completeness:** Successful search metadata without `organic_results` and without the recognized provider explicit no-results message now returns `MISSING_ORGANIC_RESULT_STATE`. Organic lists with malformed or unsafe links return `PROVIDER_RESULTS_REJECTED` instead of dropping entries and declaring adequate coverage. Rejected URLs are never fetched. A larger-than-100 organic array still fails closed as before.
3. **Provider resource cap:** `SerpApiClient.search` streams the response with a 2 MiB uncompressed byte cap, checks explicit `Content-Length` and actual bytes before JSON deserialization. The direct adapter also checks serialized sanitized payload length. Too-large bodies give `PROVIDER_BODY_TOO_LARGE`; malformed Content-Length gives a controlled error. This size is a conservative offline policy subject to revision after sampling legitimate live payload sizes. No SerpApi credits were used in this release.
4. **Reuse accounting:** `CheckOutcome.provider_calls` remains the number of **new** provider dispatches for the current HTTP invocation. When a response reuses a running or recent result it is 0, while `origin_provider_calls` stores attempts originally used to create that evidence. Both share states remain labelled in `execution_mode`. Search manifests are retained as historical evidence.
5. **URL path trust:** Operator-approved publication routes now deny encoded separators/dots, `%25` double encoding, residual percent escapes, raw backslashes, dot segments and well-known user-contributed areas *before* a document can govern. Benign encoded spaces remain supported. This is a conservative trust rule; actual issuer publication channels must still be manually corroborated.
6. **Python 3.11 on Windows:** `os.fchmod` is called only when the platform has it. Windows versions without that function inherit the evidence directory's NTFS DACL. **An operator must configure a private directory with suitable user-only permissions; the standard library fallback does not claim to set a Windows owner-only ACL.** The missing-API cross-platform regression is now included.
7. **Cancellation:** Previously offloaded `SnapshotStore.put` and `parse_snapshot` now drain already-started threads before cancellation completes, similar to the bounded fetch path. Threads are not forcibly interrupted; request cancellation can take as long as the current bounded operation. Worker admission remains limited by the API rate/concurrency controls, not a universal global thread quota.
8. **Evidence retention:** Every capture event (URL/time/source metadata) remains independently replayable and tamper-checkable. `SnapshotStore` refuses additional writes at 1024 captures or 200,000,000 bytes by default, rather than deleting historical forensic evidence. Capacity changes are not automatic. In-process lock guards allocation; multi-process shared-volume admission is **not** an atomic global quota, so restrict deployments to a single writer or use a shared filesystem/database admission coordinator.

## Prior audit test oracle adjustments

Three old tests expected malformed organic search results to be quietly filtered while preserving the good result and `OK` status. Their expectations were intentionally updated to the stricter, defensible `ERROR/PROVIDER_RESULTS_REJECTED` contract. This is a safety strengthening, not suppression of the attack.

The older audit's `one file for 25 captures` expectation conflicts with immutable capture-timestamp provenance: deleting the 24 distinct capture envelopes would make historic captures unreplayable. That test was updated to assert **25 distinct preserved events plus quota-enforced rejection beyond a configured small bound**, rather than silently discarding evidence. The new explicit capacity tests verify that an over-budget write returns a typed error and leaves existing snapshots untouched.

Two old tests expected the v0.8.4 health version; their version expectation now checks v0.8.5.

## Run the strict offline verifier

```powershell
python -m pip install -r requirements.txt
python scripts/verify_v085.py
```

Gate requirements: **all existing tests plus both independent audit suites + new boundary tests**, >=95.0% *exact* branch-aware coverage, successful synthetic E2E demonstration, publisher-wording compatibility, and three consecutive full-suite runs. Verify the same command after independent ZIP extraction.

## Outstanding and never claimed

- No live API-keyed SerpApi-to-real-issuer complete run was performed. The NCA-F scanned corrigendum / reference-variant case remains beyond automatic proven support.
- No clean Windows Python 3.11 end-to-end verifier on an actual Windows system has been run. Linux simulation of absent `fchmod` is a useful regression but not a Windows certificate.
- No Windows DACL is provisioned by this code; ensure the selected evidence directory is private before deployment.
- No multi-process atomic snapshot quota, unlimited parallel parser resource pool, or full visual validation of arbitrary HTML/PDF.
- A missing `organic_results` field can be legitimate in certain live SerpApi responses. The fail-closed policy may abstain on those; choose provider-specific allowed empty forms only after recording and independently confirming legitimate cases.
- Do not claim source completeness from search alone; unsupported/scanned content must abstain.
