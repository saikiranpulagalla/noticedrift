# Threat model and remaining attack surfaces

Search results, public pages, metadata and user notices are untrusted. SerpApi data discovers candidates and is never, by itself, authorization to govern. The parser/authority/grounding chain is not yet fully implemented; do not expose this artifact as a public definitive notice checker.

Implemented defenses: typed canonical value comparison, checked event provenance, issuer-primary formal-role gating, narrowly scoped withdrawals/cancellations, topological ordering, strong family binding, bounded query execution, safe search URL schemes, query operator filtering, explicit provider/cache provenance, raw replay checksums, anti-traversal storage keys, secret-field sanitization, and no secrets in manifests.

Outstanding P0/P1 before live product: safe source fetcher with DNS pinning/redirect revalidation to resist SSRF and rebinding; snapshot-once source bytes + verified extraction spans; independently corroborated issuer ownership/domain; semantically complete coverage calculation; noisy/multilingual/scanned PDF support either with verified extraction or explicit abstention; clean Python 3.11 verification; browser/UI injection tests; no false guarantee of completeness when Google index is stale.

Storage SHA-256 verifies local integrity only; a malicious filesystem actor able to modify both hash and payload can forge it. Provider `no_cache=true` does not guarantee that new documents are indexed immediately.
