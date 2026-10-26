"""Run reproducible engineering checks and keep every verification run separate."""

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from app.core import ROOT


def verify(output_dir):
    """Record real exits and logs; this runner never certifies clinical safety."""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    commands = [
        ("behavioral_http_cli_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]),
        ("binding_and_coverage_challenges", [sys.executable, "-m", "app.evaluate", "--output", str(output_dir / "evaluation.json")]),
        ("javascript_syntax", ["node", "--check", "app/static/app.js"]),
        ("dependency_lock", ["uv", "lock", "--check"]),
    ]
    checks = []
    for name, command in commands:
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            output = result.stdout + result.stderr
            check = {"name": name, "command": command, "exit_code": result.returncode, "status": "PASS" if result.returncode == 0 else "FAIL", "log": name + ".txt"}
            if name == "behavioral_http_cli_tests":
                match = re.search(r"Ran (\d+) tests", output)
                check["tests"] = int(match.group(1)) if match else None
                if not check["tests"]:
                    check["status"] = "FAIL"
        except (OSError, subprocess.TimeoutExpired):
            check = {"name": name, "command": command, "exit_code": None, "status": "NOT_COMPLETED", "log": name + ".txt"}
            output = "Command unavailable or timed out; completion not verified.\n"
        (output_dir / check["log"]).write_text(output or "Completed with no output.\n", encoding="utf-8")
        checks.append(check)
        print(f"{name}: {check['status']}", flush=True)
    allowed = {".py", ".js", ".json", ".html", ".css"}
    files = [p for folder in ("app", "data", "tests") for p in (ROOT / folder).rglob("*") if p.is_file() and p.suffix in allowed and "__pycache__" not in p.parts and not p.name.startswith(".")]
    files.extend(ROOT / name for name in ("pyproject.toml", "uv.lock"))
    report = {
        "release": version, "verified_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "checks": checks,
        "verified_files": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)},
        "semantic_accuracy": None, "clinical_validation": "NOT_RUN",
        "not_run": ["medical entailment benchmark", "atomic claim extraction benchmark", "clinical usefulness and safety", "browser visual checks (record separately)", "production deployment"],
    }
    (output_dir / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Run engineering checks without model calls or clinical certification")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir or ROOT / "work" / ("verification-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    try:
        report = verify(output_dir)
    except FileExistsError:
        parser.exit(2, "Output directory already exists; use a new path to preserve prior results.\n")
    print(f"Verification records: {output_dir}")
    raise SystemExit(0 if all(c["status"] == "PASS" for c in report["checks"]) else 1)


if __name__ == "__main__":
    main()
