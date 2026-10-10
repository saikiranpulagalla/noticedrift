"""Offline correctness gate for NoticeDrift v0.5.2 (no paid searches)."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def run(label: str, *args: str) -> None:
    print(f"[RUN] {label}", flush=True)
    subprocess.run([sys.executable, *args], check=True, cwd=ROOT)
    print(f"[PASS] {label}", flush=True)


def main() -> None:
    run("Compilation", "-m", "compileall", "-q", "backend/app")
    report = ROOT / ".v052_coverage.json"
    try:
        run("Full suite + branch coverage", "-m", "pytest", "--cov=backend/app/domain",
            "--cov=backend/app/search", "--cov-branch", f"--cov-report=json:{report}", "-q")
        measured = json.loads(report.read_text(encoding="utf-8"))["totals"]["percent_covered"]
        print(f"[COVERAGE] exact combined branch-aware coverage: {measured:.4f}%", flush=True)
        if measured < 95.0:
            raise SystemExit(f"RELEASE BLOCKED: exact coverage {measured:.4f}% < 95.0000%")
    finally:
        report.unlink(missing_ok=True)
    for n in range(1, 4):
        run(f"Stable full-suite execution {n}/3", "-m", "pytest", "-q")
    print("NOTICE DRIFT v0.5.2 OFFLINE CORRECTNESS GATE PASS; LIVE INGESTION NOT VERIFIED")

if __name__ == "__main__":
    main()
