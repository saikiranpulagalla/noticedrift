"""v0.8.5 combined red-team strict offline gate: inherited behavior + publisher-compatibility probes."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def run(*args):
    print('[RUN]', ' '.join(args), flush=True)
    subprocess.run([sys.executable,*args],cwd=ROOT,check=True)


def main():
    run('-m','compileall','-q','backend/app','scripts')
    coverage_file=ROOT/'.v085_coverage.json'
    try:
        run('-m','pytest','--cov=backend/app','--cov-branch',f'--cov-report=json:{coverage_file}','-q')
        coverage=json.loads(coverage_file.read_text())['totals']['percent_covered']
        print(f'[COVERAGE] exact={coverage:.6f}%',flush=True)
        if coverage<95:
            raise SystemExit('COVERAGE_BELOW_95')
    finally:
        coverage_file.unlink(missing_ok=True)
    run('scripts/real_case_probe.py')
    run('scripts/live_ncaf_check.py')
    run('scripts/demo_v07_offline.py')
    for attempt in range(1,4):
        print(f'[STABILITY] {attempt}/3',flush=True)
        run('-m','pytest','-q')
    print('PASS: v0.8.5 COMBINED INHERITED + BOTH v0.8.4 AUDITS + STRICT PROVIDER GATES. REAL LIVE SERPAPI AND ORIGINAL SOURCE BYTES ARE UNVERIFIED.',flush=True)

if __name__=='__main__':main()
