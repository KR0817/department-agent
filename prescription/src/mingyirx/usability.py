"""Local structured usability imports; no clinical records or inferred metrics."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from pathlib import Path

from . import __version__
from .io import file_sha256


PROTOCOL_VERSION = "2026-10-22-v1"
FIELDS = (
    "protocol_version", "demo_sha256", "evidence_kind", "participant_id",
    "reviewer_id", "task_id", "device", "outcome", "duration_seconds",
    "error_count", "correction_count", "satisfaction", "interpretation",
)
TASKS = (
    {
        "task_id": "pattern",
        "instruction": "Select a source and disease, locate an item pattern and its denominator, then clear the search.",
        "completion": "Locate the pattern, identify its source and denominator, and return to the unfiltered view.",
        "interpretations": ("descriptive_only", "recommendation", "unsure", "not_answered"),
    },
    {
        "task_id": "recorded_dose",
        "instruction": "Inspect a disclosed recorded gram-dose summary and a missing or suppressed dose example.",
        "completion": "Identify the recorded per-item dose and usable-patient basis; distinguish unavailable from zero dose.",
        "interpretations": ("recorded_grams_not_daily", "daily_dose", "unsure", "not_answered"),
    },
    {
        "task_id": "annual_source",
        "instruction": "Inspect an annual item view, switch source, and inspect the changed years and denominator.",
        "completion": "Distinguish source denominators and unavailable years; avoid pooling source patient counts.",
        "interpretations": ("source_denominators_separate", "pooled_patients", "unsure", "not_answered"),
    },
)
KINDS = ("synthetic_smoke", "human_declared")
ARTIFACTS = ("imported.csv", "responses.csv", "tasks.json")
MAX_INPUT_BYTES = 1024 * 1024


class UsabilityError(ValueError):
    """A structured import failed validation; source values stay withheld."""


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode("utf-8")


def _task_bytes() -> bytes:
    return _json_bytes({"protocol_version": PROTOCOL_VERSION, "tasks": TASKS})


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _new_output(output: Path) -> None:
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise UsabilityError("Output directory already exists; no files overwritten") from error


def _write_new(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)


def _read_input(path: Path) -> bytes:
    if path.suffix.lower() != ".csv":
        raise UsabilityError("Input must be a structured CSV file")
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_INPUT_BYTES + 1)
    except OSError as error:
        raise UsabilityError("Input could not be read; source path withheld") from error
    if len(payload) > MAX_INPUT_BYTES:
        raise UsabilityError("Input exceeds the one-megabyte local import limit")
    return payload


def _integer(row: dict[str, str], field: str, minimum: int, maximum: int, number: int) -> int:
    value = row[field]
    if not re.fullmatch(r"0|[1-9][0-9]{0,3}", value) or not minimum <= int(value) <= maximum:
        raise UsabilityError(f"Row {number}: invalid {field}; value withheld")
    return int(value)


def _validate_bytes(
    payload: bytes, evidence_kind: str, human_declared: bool,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    if evidence_kind not in KINDS:
        raise UsabilityError("Unsupported evidence kind")
    if type(human_declared) is not bool or (evidence_kind == "human_declared") != human_declared:
        raise UsabilityError("Human records require an explicit matching human declaration")
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""), strict=True)
        if reader.fieldnames != list(FIELDS):
            raise UsabilityError("CSV columns must match the protocol; extra or missing fields are blocked")
        rows = list(reader)
    except (UnicodeError, csv.Error) as error:
        raise UsabilityError("Invalid UTF-8 CSV; source content withheld") from error
    if not rows:
        raise UsabilityError("No responses; blank templates cannot be frozen")
    sessions: dict[str, tuple[str, str]] = {}
    keys: set[tuple[str, str]] = set()
    demo_hashes: set[str] = set()
    task_options = {task["task_id"]: task["interpretations"] for task in TASKS}
    for number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise UsabilityError(f"Row {number}: malformed response row")
        if any(not value or value != value.strip() or len(value) > 64 for value in row.values()):
            raise UsabilityError(f"Row {number}: blank or malformed field; value withheld")
        if row["protocol_version"] != PROTOCOL_VERSION or row["evidence_kind"] != evidence_kind:
            raise UsabilityError(f"Row {number}: protocol or evidence kind mismatch")
        if not re.fullmatch(r"[a-f0-9]{64}", row["demo_sha256"]):
            raise UsabilityError(f"Row {number}: invalid demo hash")
        for field, prefix in (("participant_id", "P"), ("reviewer_id", "R")):
            if not re.fullmatch(prefix + r"-[0-9]{4}", row[field]):
                raise UsabilityError(f"Row {number}: invalid pseudonymous {field}; value withheld")
        task_id = row["task_id"]
        if task_id not in task_options or row["interpretation"] not in task_options[task_id]:
            raise UsabilityError(f"Row {number}: invalid task or interpretation category")
        if row["device"] not in {"desktop", "mobile"} or row["outcome"] not in {"completed", "abandoned"}:
            raise UsabilityError(f"Row {number}: invalid device or outcome category")
        if row["outcome"] == "completed" and row["interpretation"] == "not_answered":
            raise UsabilityError(f"Row {number}: completed task requires an interpretation response")
        _integer(row, "duration_seconds", 1, 7200, number)
        errors = _integer(row, "error_count", 0, 999, number)
        _integer(row, "correction_count", 0, errors, number)
        _integer(row, "satisfaction", 1, 5, number)
        key = (row["participant_id"], task_id)
        if key in keys:
            raise UsabilityError(f"Row {number}: duplicate participant-task response")
        keys.add(key)
        session = (row["reviewer_id"], row["device"])
        if sessions.setdefault(row["participant_id"], session) != session:
            raise UsabilityError(f"Row {number}: session observer or device changed")
        demo_hashes.add(row["demo_sha256"])
    if len(demo_hashes) != 1:
        raise UsabilityError("All records must reference the same fixed demo hash")
    if len(keys) != len(sessions) * len(TASKS):
        raise UsabilityError("Each participant requires exactly the three protocol tasks")
    rows.sort(key=lambda row: (row["participant_id"], row["task_id"]))
    return rows, {
        "gate": "PASS", "protocol_version": PROTOCOL_VERSION,
        "demo_sha256": next(iter(demo_hashes)), "evidence_kind": evidence_kind,
        "evidence_state": ("SYNTHETIC_SOFTWARE_CHECK_ONLY" if evidence_kind == "synthetic_smoke"
                           else "HUMAN_PARTICIPATION_DECLARED_UNVERIFIED"),
        "records": len(rows), "participants": len(sessions),
        "human_declaration": human_declared, "clinical_evidence": False,
        "scope": "Structured usability records only; no identity verification or clinical performance inference",
    }


def prepare_template(output: Path, demo_sha256: str) -> dict[str, object]:
    """Create blank task responses without representing any participation."""
    if not re.fullmatch(r"[a-f0-9]{64}", demo_sha256):
        raise UsabilityError("A lowercase SHA-256 for the fixed demo is required")
    rows = []
    for task in TASKS:
        row = dict.fromkeys(FIELDS, "")
        row.update(protocol_version=PROTOCOL_VERSION, demo_sha256=demo_sha256, task_id=task["task_id"])
        rows.append(row)
    _new_output(output)
    _write_new(output / "responses.csv", _csv_bytes(rows))
    _write_new(output / "tasks.json", _task_bytes())
    return {"gate": "PASS", "protocol_version": PROTOCOL_VERSION,
            "evidence_state": "NO_PARTICIPATION_DATA", "clinical_evidence": False}


def validate_responses(input_path: Path, evidence_kind: str, *, human_declared: bool = False) -> dict[str, object]:
    """Validate a complete declared session without computing performance claims."""
    return _validate_bytes(_read_input(input_path), evidence_kind, human_declared)[1]


def freeze_responses(
    input_path: Path, output: Path, evidence_kind: str, *, human_declared: bool = False,
) -> dict[str, object]:
    """Freeze one validated byte snapshot and write its completion manifest last."""
    payload = _read_input(input_path)
    rows, summary = _validate_bytes(payload, evidence_kind, human_declared)
    artifacts = {"imported.csv": payload, "responses.csv": _csv_bytes(rows), "tasks.json": _task_bytes()}
    manifest = dict(summary, schema_version=1, software_version=__version__,
                    module_sha256=file_sha256(Path(__file__)), import_sha256=_sha256(payload),
                    artifacts={name: _sha256(content) for name, content in artifacts.items()})
    _new_output(output)
    for name, content in artifacts.items():
        _write_new(output / name, content)
    _write_new(output / "manifest.json", _json_bytes(manifest))
    return manifest


def verify_frozen(input_dir: Path) -> dict[str, object]:
    """Check exact file membership, artifact hashes and the structured contract."""
    try:
        if {path.name for path in input_dir.iterdir()} != set(ARTIFACTS) | {"manifest.json"}:
            raise UsabilityError("Frozen package is incomplete or contains unexpected files")
        if any(path.is_symlink() or not path.is_file() for path in input_dir.iterdir()):
            raise UsabilityError("Frozen artifacts must be ordinary files")
        manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise UsabilityError("Unsupported frozen manifest schema")
        hashes = manifest.get("artifacts")
        if not isinstance(hashes, dict) or set(hashes) != set(ARTIFACTS):
            raise UsabilityError("Frozen artifact hash entries do not match the contract")
        for name in ARTIFACTS:
            if file_sha256(input_dir / name) != hashes[name]:
                raise UsabilityError("Frozen artifact hash mismatch; source content withheld")
        original = _read_input(input_dir / "imported.csv")
        rows, summary = _validate_bytes(original, manifest.get("evidence_kind"), manifest.get("human_declaration"))
        if any(manifest.get(key) != value for key, value in summary.items()):
            raise UsabilityError("Frozen summary does not match its imported records")
        if manifest.get("import_sha256") != _sha256(original):
            raise UsabilityError("Frozen import hash does not match")
        if (input_dir / "responses.csv").read_bytes() != _csv_bytes(rows):
            raise UsabilityError("Frozen canonical responses do not match the imported records")
        if (input_dir / "tasks.json").read_bytes() != _task_bytes():
            raise UsabilityError("Frozen task definitions do not match this protocol version")
        if not isinstance(manifest.get("module_sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", manifest["module_sha256"]):
            raise UsabilityError("Frozen module provenance is invalid")
        return dict(summary, artifact_check="PASS")
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
        raise UsabilityError("Frozen package could not be verified; content and path withheld") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    template = commands.add_parser("template", help="Create an unfilled three-task response template")
    template.add_argument("--demo-sha256", required=True)
    template.add_argument("--output", type=Path, required=True)
    for name in ("validate", "freeze"):
        command = commands.add_parser(name)
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--evidence-kind", choices=KINDS, required=True)
        command.add_argument("--human-declared", action="store_true")
        if name == "freeze":
            command.add_argument("--output", type=Path, required=True)
    commands.add_parser("verify").add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "template":
            result = prepare_template(args.output, args.demo_sha256)
        elif args.command == "verify":
            result = verify_frozen(args.input)
        elif args.command == "validate":
            result = validate_responses(args.input, args.evidence_kind, human_declared=args.human_declared)
        else:
            result = freeze_responses(args.input, args.output, args.evidence_kind, human_declared=args.human_declared)
    except (UsabilityError, OSError) as error:
        message = str(error) if isinstance(error, UsabilityError) else "Local I/O failed; path and content withheld"
        print(json.dumps({"gate": "BLOCK", "message": message}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
