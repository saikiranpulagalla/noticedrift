from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(label: str, args: list[str]) -> None:
    print(f"[RUN] {label}")
    proc = subprocess.run(args, cwd=ROOT)
    if proc.returncode != 0:
        print(f"[FAIL] {label}")
        raise SystemExit(proc.returncode)
    print(f"[PASS] {label}")


def main() -> None:
    run("Compile domain", [sys.executable, "-m", "compileall", "-q", "backend/app/domain"])
    run("Domain tests + branch coverage", [
        sys.executable, "-m", "pytest",
        "--cov=backend/app/domain", "--cov-branch", "--cov-fail-under=95", "-q"
    ])
    # Flake check: run deterministic suite three consecutive times.
    for i in range(1, 4):
        run(f"Stability run {i}/3", [sys.executable, "-m", "pytest", "-q"])

    print("\nNOTICE DRIFT OFFLINE CORE GATE: PASS")


if __name__ == "__main__":
    main()
