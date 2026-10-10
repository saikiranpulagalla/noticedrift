"""Publicly reviewed reference case. NOT captured HTML/PDF evidence.

This contextual example is intentionally NOT converted to governing NoticeDocument,
GovernanceEvent, or a LIVE_CHECK response: its source bytes and search manifest
were not captured by the application. Data is reviewed from the official portal.
"""
from __future__ import annotations


def official_reference_case() -> dict:
    return {
        "case_id": "ncaf-teaching-associates-sep-2026",
        "organization": "National Communications Academy–Finance (NCA-F)",
        "program": "Teaching Associates — two posts",
        "case_type": "REAL_OFFICIAL_SOURCE_REFERENCE",
        "notice_reference": "4-22/Teaching Associate/2026-NCA-F",
        "original_deadline": "2026-10-01",
        "revised_deadline": "2026-10-26",
        "correction_published": "2026-09-17",
        "other_material_change": {
            "field": "Essential qualification (one post)",
            "original": "Physiology",
            "corrected": "Psychology",
            "machine_verified": False,
            "note": "Visible in the official bilingual corrigendum PDF; outside the supported deadline-only resolver.",
        },
        "references": [
            {
                "kind": "Original official publication",
                "url": "https://nicf.gov.in/2026/09/14/vacancy-circular-for-two-02-posts-of-teaching-associates/",
            },
            {
                "kind": "Official corrigendum webpage",
                "url": "https://nicf.gov.in/2026/09/17/vacancy-circular-for-two-02-posts-of-teaching-associates-2/",
            },
            {
                "kind": "Official corrigendum PDF",
                "url": "https://nicf.gov.in/wp-content/uploads/2026/09/Corrigendum-of-Vacancy-circular-1.pdf",
            },
        ],
        "reviewed_excerpt": "The revised deadline for receipt of applications is now 26th October 2026 instead of 1st October 2026.",
        "provenance_level": "PUBLIC_WEB_REVIEWED_TRANSCRIPTION",
        "application_snapshot_verified": False,
        "serpapi_run_executed": False,
        "automated_governance_verdict": None,
        "disclosure": (
            "Real facts reviewed on issuer pages and a visible PDF. Not a captured, "
            "hash-verified application snapshot; no live SerpApi search performed for this case."
        ),
    }
