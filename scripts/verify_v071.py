"""Strict offline safety release gate. Uses no live SerpApi credentials."""
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
    run('Compilation','-m','compileall','-q','backend/app')
    report=ROOT/'.v071_coverage.json'
    try:
        run('Full suite and branch-aware coverage','-m','pytest',
            '--cov=backend/app','--cov-branch',f'--cov-report=json:{report}','-q')
        exact=json.loads(report.read_text())['totals']['percent_covered']
        print(f'[COVERAGE] exact={exact:.6f}%',flush=True)
        if exact < 95.0:
            raise SystemExit(f'FAIL: exact coverage below 95% ({exact:.6f}%)')
    finally:
        report.unlink(missing_ok=True)
    run('Synthetic source-bytes → verdict demo','scripts/demo_v07_offline.py')
    for n in range(1,4):
        run(f'Full-suite stability {n}/3','-m','pytest','-q')
    print('PASS: v0.7.1 OFFLINE ADVERSARIAL GATE. LIVE SERPAPI/ISSUER NOT VERIFIED.',flush=True)
if __name__ == '__main__':
    main()
