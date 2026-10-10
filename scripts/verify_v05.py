from __future__ import annotations
import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def run(label, args):
    print(f"[RUN] {label}")
    p = subprocess.run(args, cwd=ROOT)
    if p.returncode:
        print(f"[FAIL] {label}")
        raise SystemExit(p.returncode)
    print(f"[PASS] {label}")

def main():
    run("Compile backend core", [sys.executable, "-m", "compileall", "-q", "backend/app/domain", "backend/app/search"])
    run("Domain + search tests with branch coverage", [sys.executable, "-m", "pytest", "--cov=backend/app/domain", "--cov=backend/app/search", "--cov-branch", "--cov-fail-under=95", "-q"])
    for i in range(1, 4):
        run(f"Stability run {i}/3", [sys.executable, "-m", "pytest", "-q"])
    print("\nNOTICE DRIFT v0.5 GATE: PASS")

if __name__ == "__main__":
    main()
