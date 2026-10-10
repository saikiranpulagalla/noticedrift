"""Operator-only NCA-F live smoke. No key → no network, no simulated success.

Requires independently reviewed issuer-host attestation, operator credentials,
and explicit --execute consent to spend SerpApi credits. Results stay on disk.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))

from app.application.models import NoticeCheckRequest
from app.search.planner import plan_queries
from app.domain.normalization import normalize_reference

REFERENCE = '4-22/Estt./Teaching Associates/2026-NCA-F'
TITLE = 'Teaching Associates'
ORIGINAL_PDF = 'https://nicf.gov.in/wp-content/uploads/2026/09/vacancy-circular-two-02-posts-teaching-associates.pdf'
ISSUER = 'ncaf'


def preflight(issuer_manifest: Path | None) -> dict:
    plan=plan_queries(reference_number=REFERENCE,issuer_name='National Communications Academy Finance',title=TITLE,official_domain='nicf.gov.in')
    literal=normalize_reference(REFERENCE)
    if len(plan.queries)<4 or any(f'"{literal}"' not in q.query for q in plan.queries[:4]):
        raise RuntimeError('SEARCH_REFERENCE_NOT_PRESERVED')
    return {'mode':'DRY_RUN_NO_REQUESTS', 'queries':[{'query':q.query,'purpose':q.purpose.value,'tier':q.tier.value} for q in plan.queries],
            'max_search_calls':min(8,len(plan.queries)), 'manifest_path':str(issuer_manifest) if issuer_manifest else None,
            'original_url':ORIGINAL_PDF,'reference':REFERENCE,
            'limitations':['Official original and corrigendum use differing reference forms',
                           'The official corrigendum PDF is image-based, beyond text-only admission',
                           'The corrigendum contains an additional eligibility change',
                           'A live verdict may be UNRESOLVED even after successful search']}


async def perform(manifest: Path, evidence_dir: Path) -> dict:
    from app.api.main import configured_workflow
    os.environ['NOTICEDRIFT_ISSUER_ATTESTATIONS']=str(manifest.resolve())
    os.environ['NOTICEDRIFT_EVIDENCE_DIR']=str(evidence_dir.resolve())
    workflow = configured_workflow()
    if workflow is None:
        raise RuntimeError('OPERATOR_CONFIGURATION_INVALID')
    req=NoticeCheckRequest(issuer_id=ISSUER,issuer_name='National Communications Academy Finance',
        reference_number=REFERENCE,supplied_deadline=date(2026,10,1),
        notice_title=TITLE,
        original_url=ORIGINAL_PDF,as_of=datetime.now(timezone.utc))
    try:
        result=await workflow.check(req,fresh=True)
        return result.model_dump(mode='json')
    finally:
        await workflow.executor.client.aclose()


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description='Operator-only, bounded NCA-F live check; dry-run default')
    p.add_argument('--execute',action='store_true', help='Explicit consent to real SerpApi API calls (may incur quota)')
    p.add_argument('--authority-manifest',type=Path,default=None)
    p.add_argument('--evidence-dir',type=Path,default=ROOT/'.noticedrift-evidence')
    p.add_argument('--output',type=Path,default=None)
    args=p.parse_args(argv)
    info=preflight(args.authority_manifest)
    if not args.execute:
        print(json.dumps(info,indent=2))
        return 0
    if not os.environ.get('SERPAPI_API_KEY'):
        print('REFUSED: SERPAPI_API_KEY not present; no network calls made.',file=sys.stderr)
        return 2
    if args.authority_manifest is None or not args.authority_manifest.is_file():
        print('REFUSED: operator-authored authority manifest required.',file=sys.stderr)
        return 2
    try:
        result=asyncio.run(perform(args.authority_manifest,args.evidence_dir))
    except RuntimeError as exc:
        print('REFUSED: '+str(exc),file=sys.stderr)
        return 2
    # Output is JSON, no raw API key, no false claims about success.
    payload={'run_type':'LIVE_ATTEMPT_ACTUAL_PROVIDER_AND_SOURCE_RESULTS',
             'analysis':result, 'limits':info['limitations']}
    serialized=json.dumps(payload,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        # Never overwrite a previous run or silently swap its identity.
        with args.output.open('x',encoding='utf-8') as f:
            f.write(serialized+'\n')
        print('Saved '+str(args.output))
    else:
        print(serialized)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
