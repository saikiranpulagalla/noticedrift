"""Real-NCA-F evidence *compatibility* probe, never a governing-verdict engine.

No external request, SerpApi key, or official-source authentication occurs here.
Its reviewed-text mode operates on short quotations independently read from the
issuer's published material, so no captured-website SHA or LIVE status is claimed.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

NCAF_ORIGINAL_URL = 'https://nicf.gov.in/wp-content/uploads/2026/09/vacancy-circular-two-02-posts-teaching-associates.pdf'
NCAF_CORRECTION_URL = 'https://nicf.gov.in/wp-content/uploads/2026/09/Corrigendum-of-Vacancy-circular-1.pdf'
NCAF_CORRECTION_PAGE = 'https://nicf.gov.in/2026/09/17/vacancy-circular-for-two-02-posts-of-teaching-associates-2/'
# These are publisher excerpts checked by independent reference review. They are
# NOT copies of the website/PDF bytes, and must not be entered into SnapshotStore.
REVIEWED_ORIGINAL = 'Last date to receive application is 1st October, 2026.'
REVIEWED_CORRECTION = 'The revised deadline for receipt of applications is now 26th October 2026 instead of 1st October 2026.'
REVIEWED_OTHER_CHANGE = 'Essential qualification also corrected for one post (Physiology to Psychology).'

MONTHS = '|'.join(('January','February','March','April','May','June','July','August','September','October','November','December'))
DATE = rf'\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS}),?\s+\d{{4}}'
# Avoid permissive keyword-only matching. Require both dates in one affirmative clause.
CHANGE = re.compile(
    rf'(?i)\b(?:revised\s+deadline\s+for\s+receipt\s+of\s+applications\s+is\s+now|'
    rf'last\s+date\s+for\s+(?:the\s+)?submission\s+of\s+applications\s+is\s+now)\s+'
    rf'(?P<new>{DATE})\s+instead\s+of\s+(?P<old>{DATE})\b'
)
OLD = re.compile(rf'(?i)\blast\s+date\s+to\s+receive\s+application\s+is\s+(?P<old>{DATE})\b')
NEGATED = re.compile(r'(?i)\b(?:withdrawn|rescinded|revoked|not\s+valid|false\s+rumou?r|not\s+applicable|superseded|only\s+proposed)\b')

class ReviewedExcerptError(ValueError):
    pass


def _date(raw: str) -> date:
    cleaned = re.sub(r'(?i)(\d)(st|nd|rd|th)\b', r'\1', raw.strip())
    cleaned = cleaned.replace(',', '')
    try:
        return datetime.strptime(cleaned, '%d %B %Y').date()
    except ValueError:
        raise ReviewedExcerptError('INVALID_REVIEWED_DATE') from None


def reviewed_deadlines(original: str, correction: str) -> dict:
    """Adversarially conservative *text-only* comparison; NOT an authority check."""
    if NEGATED.search(original + '\n' + correction):
        raise ReviewedExcerptError('CONTRADICTORY_CONTEXT')
    old_matches = list(OLD.finditer(original))
    new_matches = list(CHANGE.finditer(correction))
    if len(old_matches) != 1 or len(new_matches) != 1:
        raise ReviewedExcerptError('AMBIGUOUS_OR_UNSUPPORTED_WORDING')
    original_value = _date(old_matches[0]['old'])
    described_old = _date(new_matches[0]['old'])
    revised = _date(new_matches[0]['new'])
    if original_value != described_old or revised <= described_old:
        raise ReviewedExcerptError('INVALID_DEADLINE_TRANSITION')
    return {
        'classification': 'REVIEWED_EXCERPT_COMPATIBLE_NOT_AUTOMATICALLY_GOVERNING',
        'original_deadline': original_value.isoformat(),
        'revised_deadline': revised.isoformat(),
        'source_lineage': 'NOT_ATTESTED_FROM_APPLICATION_CAPTURE',
        'serpapi_verified': False,
        'captured_raw_sources_verified': False,
        'unresolved_other_change': 'Essential qualification of one post is outside deadline-only scope',
    }


def probe_local_file(path: Path, *, mime: str, source_url: str) -> dict:
    """Inspect user-supplied local bytes without claiming verified network provenance."""
    from app.sources.models import SourceSnapshot
    from app.sources.parse import parse_snapshot
    if not path.is_file():
        raise FileNotFoundError(path)
    # The same maximum is used regardless of CLI caller; memory remains bounded.
    if path.stat().st_size > 10_000_000:
        raise ReviewedExcerptError('SOURCE_TOO_LARGE')
    body = path.read_bytes()
    snap = SourceSnapshot(source_url=source_url, final_url=source_url,
         captured_at=datetime.now(timezone.utc), content_type=mime,
         body=body, body_sha256=sha256(body).hexdigest())
    parsed = parse_snapshot(snap)
    return {
        'source_url': source_url,
        'provenance': 'OPERATOR_SUPPLIED_FILE_UNVERIFIED_NETWORK_ORIGIN',
        'body_sha256': snap.body_sha256,
        'text_sha256': parsed.normalized_text_sha256,
        'parser_status': parsed.status,
        'warnings': list(parsed.warning_codes),
        'extracted_character_count': len(parsed.text),
        'contains_original_deadline_phrase': bool(OLD.search(parsed.text)),
        'contains_revised_deadline_phrase': bool(CHANGE.search(parsed.text)),
        'governing_evidence_admitted': False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Offline NCA-F publisher-wording compatibility and optional local-file parser probe')
    parser.add_argument('--original-pdf', type=Path)
    parser.add_argument('--corrigendum-pdf', type=Path)
    parser.add_argument('--corrigendum-html', type=Path)
    args = parser.parse_args(argv)
    result = {'case':'NCA-F Teaching Associates Sept 2026',
              'mode':'MANUALLY_REVIEWED_TEXT_NO_PROVIDER_REQUEST',
              'reviewed': reviewed_deadlines(REVIEWED_ORIGINAL, REVIEWED_CORRECTION),
              'official_urls': [NCAF_ORIGINAL_URL,NCAF_CORRECTION_URL,NCAF_CORRECTION_PAGE],
              'additional_material_change': REVIEWED_OTHER_CHANGE,
              'local_files': []}
    for path,mime,url in ((args.original_pdf,'application/pdf',NCAF_ORIGINAL_URL),
                          (args.corrigendum_pdf,'application/pdf',NCAF_CORRECTION_URL),
                          (args.corrigendum_html,'text/html',NCAF_CORRECTION_PAGE)):
        if path:
            result['local_files'].append(probe_local_file(path,mime=mime,source_url=url))
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
