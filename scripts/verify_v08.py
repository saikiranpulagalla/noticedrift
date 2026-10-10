"""v0.8 strict offline gate. Requires no SerpApi key, network or browser."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run(name: str, *args: str):
    print(f'[RUN] {name}',flush=True)
    subprocess.run([sys.executable,*args],cwd=ROOT,check=True)
    print(f'[PASS] {name}',flush=True)

def main():
    run('Compilation','-m','compileall','-q','backend/app')
    report=ROOT/'.v08_coverage.json'
    try:
        run('Full suite + branch-aware coverage','-m','pytest','--cov=backend/app',
            '--cov-branch',f'--cov-report=json:{report}','-q')
        exact=json.loads(report.read_text(encoding='utf-8'))['totals']['percent_covered']
        print(f'[COVERAGE] exact={exact:.6f}%',flush=True)
        if exact < 95.0:
            raise SystemExit(f'FAIL: exact branch coverage below 95% ({exact:.6f}%)')
    finally:
        report.unlink(missing_ok=True)
    run('Judge HTTP interface + synthetic E2E','-m','pytest','backend/tests/judge','-q')
    run('Original synthetic E2E workflow','scripts/demo_v07_offline.py')
    for i in range(1,4):
        run(f'Full-suite stability {i}/3','-m','pytest','-q')
    print('PASS: NoticeDrift v0.8 OFFLINE JUDGE GATE. LIVE SERPAPI/ISSUER NOT VERIFIED.',flush=True)
if __name__=='__main__':main()
