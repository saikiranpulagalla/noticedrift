"""Strict zero-SerpApi-credits v0.7 end-to-end regression verifier."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run(title,*args):
    print(f'[RUN] {title}',flush=True)
    subprocess.run([sys.executable,*args],cwd=ROOT,check=True)
    print(f'[PASS] {title}',flush=True)

def main():
    run('Python compilation','-m','compileall','-q','backend/app')
    report=ROOT/'.v07_coverage.json'
    try:
        run('Full-suite + branch coverage','-m','pytest','--cov=backend/app',
            '--cov-branch',f'--cov-report=json:{report}','-q')
        exact=json.loads(report.read_text(encoding='utf-8'))['totals']['percent_covered']
        print(f'[COVERAGE] exact branch-aware {exact:.6f}%',flush=True)
        if exact < 95.0:
            raise SystemExit(f'FAIL: coverage {exact:.6f}% below 95%')
    finally:
        report.unlink(missing_ok=True)
    run('Bytes-to-verdict synthetic end-to-end demo','scripts/demo_v07_offline.py')
    for i in range(1,4):
        run(f'Stability {i}/3','-m','pytest','-q')
    print('PASS: v0.7 SYNTHETIC/OFFLINE E2E GATE; LIVE ISSUER/SEARCH DEMO NOT VERIFIED',flush=True)
if __name__=='__main__':
    main()
