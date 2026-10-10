"""Strict zero-network source-ingestion gate; real network/issuer verification remain OPEN."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(title: str, *cmd: str):
    print(f'[RUN] {title}',flush=True)
    subprocess.run([sys.executable,*cmd],cwd=ROOT,check=True)
    print(f'[PASS] {title}',flush=True)


def main():
    run('Python compilation','-m','compileall','-q','backend/app')
    report = ROOT / '.v06_coverage.json'
    try:
        run('Full suite, ingestion, trust and branch coverage','-m','pytest',
            '--cov=backend/app','--cov-branch',f'--cov-report=json:{report}','-q')
        value=json.loads(report.read_text(encoding='utf-8'))['totals']['percent_covered']
        print(f'[COVERAGE] combined branch-aware exact={value:.5f}%',flush=True)
        if value < 95:
            raise SystemExit(f'BLOCKED: exact coverage <95% ({value:.5f}%)')
    finally:
        report.unlink(missing_ok=True)
    run('Synthetic source-bytes-to-grounded-document proof','scripts/demo_v06_offline.py')
    for idx in range(1,4):
        run(f'Stability run {idx}/3','-m','pytest','-q')
    print('PASS: v0.6 OFFLINE INGESTION GATE; LIVE SOURCE/ISSUER/E2E UNVERIFIED',flush=True)

if __name__=='__main__':
    main()
