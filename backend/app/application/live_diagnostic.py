"""Sanitized, static facts from the latest operator-recorded live search.

This is a judge-facing diagnostic, not evidence admitted to the resolver.  It
contains no credentials, URLs, queries, provider payloads, source bytes, or
authority attestations.  In particular it must not be confused with a live
check or an official-source capture.
"""
from __future__ import annotations


def latest_live_search_diagnostic() -> dict[str, object]:
    """Return the immutable summary approved for local judge presentation."""
    return {
        "kind": "SANITIZED_RECORDED_LIVE_SEARCH_DIAGNOSTIC",
        "provider": "SerpApi",
        "provider_attempts": 6,
        "completed_attempts": 2,
        "timed_out_attempts": 4,
        "coverage": "INSUFFICIENT",
        "verdict": "UNRESOLVED",
        "official_source_captures": 0,
        "source_evidence_authenticated": False,
        "disclosure": (
            "This is a sanitized record of a genuine provider search run. "
            "It is not an official-source capture or a verified notice result."
        ),
        "attempts": [
            {"purpose": "IDENTITY", "status": "OK", "elapsed_ms": 1547},
            {"purpose": "CORE_CORRIGENDUM", "status": "TIMEOUT", "elapsed_ms": 15016,
             "timeout_kind": "TOTAL_ATTEMPT_DEADLINE"},
            {"purpose": "CORE_EXTENSION", "status": "OK", "elapsed_ms": 937},
            {"purpose": "CORE_CANCELLATION", "status": "TIMEOUT", "elapsed_ms": 15016,
             "timeout_kind": "TOTAL_ATTEMPT_DEADLINE"},
            {"purpose": "OFFICIAL_SITE_CORRIGENDUM", "status": "TIMEOUT", "elapsed_ms": 15016,
             "timeout_kind": "TOTAL_ATTEMPT_DEADLINE"},
            {"purpose": "OFFICIAL_SOURCE_IDENTITY", "status": "TIMEOUT", "elapsed_ms": 15016,
             "timeout_kind": "TOTAL_ATTEMPT_DEADLINE"},
        ],
    }
