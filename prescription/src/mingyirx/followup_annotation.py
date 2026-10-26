"""Local coded follow-up annotation metadata; no clinical narrative imports."""
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


PROTOCOL_VERSION = "followup-20261023-v1"
FIELDS = (
    "protocol_version", "contract_sha256", "evidence_sha256", "evidence_kind",
    "case_id", "reviewer_id", "adjacency", "preprescription_availability",
    "symptom_change", "syndrome_change", "independent_syndrome_label",
    "physician_provenance", "outcome_timing",
)
OPTIONS = {
    "adjacency": ("verified", "not_adjacent", "unknown"),
    "preprescription_availability": ("before_prescription", "after_prescription", "unknown", "not_recorded"),
    "symptom_change": ("improved", "stable", "worsened", "mixed", "not_assessable"),
    "syndrome_change": ("changed", "unchanged", "not_assessable"),
    "independent_syndrome_label": ("independent_declared", "prescription_derived", "not_available", "unknown"),
    "physician_provenance": ("verified_identifier", "absent", "unverified"),
    "outcome_timing": ("later_followup", "same_visit", "not_available", "unknown"),
}
TASKS = (
    {"task": "adjacent_pair", "instruction": "Check the original visit sequence; do not reconnect around an excluded visit."},
    {"task": "preprescription_record", "instruction": "Establish that recorded symptom and syndrome changes were available before the current prescription."},
    {"task": "independent_syndrome", "instruction": "Declare the provenance of the syndrome label; do not derive a diagnostic reference from the current prescription."},
    {"task": "physician_provenance", "instruction": "Verify the clinician identifier from its authorized source; filenames are not evidence."},
    {"task": "outcome_timing", "instruction": "Distinguish later treatment outcomes from same-visit observations and adjustment decisions."},
)
KINDS = ("synthetic_smoke", "human_declared")
ARTIFACTS = ("imported.csv", "annotations.csv", "tasks.json")
MAX_INPUT_BYTES = 1024 * 1024


class AnnotationError(ValueError):
    """The local metadata import failed; record values remain withheld."""


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _csv_bytes(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _tasks_bytes() -> bytes:
    return _json_bytes({"protocol_version": PROTOCOL_VERSION, "fields": FIELDS,
                        "coded_options": OPTIONS, "tasks": TASKS,
                        "scope": "Structured reviewer declarations only; no independent verification of clinical validity"})


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _check_hashes(contract_sha256: str, evidence_sha256: str) -> None:
    if any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
           for value in (contract_sha256, evidence_sha256)):
        raise AnnotationError("Fixed contract and evidence SHA-256 values are required")


def _new_output(output: Path) -> None:
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise AnnotationError("Output already exists; no files overwritten") from error


def _write_new(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)


def _read_input(path: Path) -> bytes:
    if path.suffix.lower() != ".csv":
        raise AnnotationError("Input must be a structured CSV file")
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_INPUT_BYTES + 1)
    except OSError as error:
        raise AnnotationError("Input could not be read; path and content withheld") from error
    if len(payload) > MAX_INPUT_BYTES:
        raise AnnotationError("Input exceeds the one-megabyte limit")
    return payload


def _validate_bytes(payload: bytes, contract_sha256: str, evidence_sha256: str,
                    evidence_kind: str, human_declared: bool) -> tuple[list[dict[str, str]], dict]:
    _check_hashes(contract_sha256, evidence_sha256)
    if evidence_kind not in KINDS or type(human_declared) is not bool:
        raise AnnotationError("Unsupported evidence kind or declaration")
    if (evidence_kind == "human_declared") != human_declared:
        raise AnnotationError("Human metadata requires an explicit matching human declaration")
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""), strict=True)
        if reader.fieldnames != list(FIELDS):
            raise AnnotationError("CSV columns must exactly match the coded protocol")
        rows = list(reader)
    except (UnicodeError, csv.Error) as error:
        raise AnnotationError("Invalid UTF-8 CSV; content withheld") from error
    if not rows:
        raise AnnotationError("Blank templates cannot be validated or frozen")
    keys = set()
    for number, row in enumerate(rows, start=2):
        if None in row or any(not isinstance(value, str) or not value or value != value.strip()
                              or len(value) > 64 for value in row.values()):
            raise AnnotationError(f"Row {number}: blank or malformed metadata; values withheld")
        expected = {"protocol_version": PROTOCOL_VERSION, "contract_sha256": contract_sha256,
                    "evidence_sha256": evidence_sha256, "evidence_kind": evidence_kind}
        if any(row[field] != value for field, value in expected.items()):
            raise AnnotationError(f"Row {number}: protocol, evidence or fixed hash mismatch")
        for field, prefix in (("case_id", "C"), ("reviewer_id", "R")):
            if not re.fullmatch(prefix + r"-[0-9]{4}", row[field]):
                raise AnnotationError(f"Row {number}: invalid pseudonymous code; value withheld")
        if any(row[field] not in choices for field, choices in OPTIONS.items()):
            raise AnnotationError(f"Row {number}: unsupported coded response; value withheld")
        if (row["preprescription_availability"] != "before_prescription"
                and (row["symptom_change"] != "not_assessable" or row["syndrome_change"] != "not_assessable")):
            raise AnnotationError(f"Row {number}: change labels require declared pre-prescription availability")
        if (row["syndrome_change"] != "not_assessable"
                and row["independent_syndrome_label"] != "independent_declared"):
            raise AnnotationError(f"Row {number}: syndrome change requires a declared independent reference")
        key = row["case_id"], row["reviewer_id"]
        if key in keys:
            raise AnnotationError(f"Row {number}: duplicate case-reviewer record")
        keys.add(key)
    rows.sort(key=lambda row: (row["case_id"], row["reviewer_id"]))
    return rows, {"gate": "PASS", "protocol_version": PROTOCOL_VERSION,
                  "contract_sha256": contract_sha256, "evidence_sha256": evidence_sha256,
                  "evidence_kind": evidence_kind, "human_declaration": human_declared,
                  "evidence_state": ("SYNTHETIC_SOFTWARE_CHECK_ONLY" if evidence_kind == "synthetic_smoke"
                                     else "HUMAN_ANNOTATION_DECLARED_UNVERIFIED"),
                  "records": len(rows), "cases": len({row["case_id"] for row in rows}),
                  "reviewers": len({row["reviewer_id"] for row in rows}),
                  "clinical_evidence": False, "independent_reference_verified": False,
                  "scope": "Coded annotation metadata only; no association estimate or clinical validity established"}


def prepare_template(output: Path, contract_sha256: str, evidence_sha256: str) -> dict:
    _check_hashes(contract_sha256, evidence_sha256)
    row = dict.fromkeys(FIELDS, "")
    row.update(protocol_version=PROTOCOL_VERSION, contract_sha256=contract_sha256, evidence_sha256=evidence_sha256)
    _new_output(output)
    _write_new(output / "annotations.csv", _csv_bytes([row]))
    _write_new(output / "tasks.json", _tasks_bytes())
    return {"gate": "PASS", "evidence_state": "NO_ANNOTATIONS_COLLECTED", "clinical_evidence": False}


def validate_annotations(input_path: Path, contract_sha256: str, evidence_sha256: str,
                         evidence_kind: str, *, human_declared: bool = False) -> dict:
    return _validate_bytes(_read_input(input_path), contract_sha256, evidence_sha256, evidence_kind, human_declared)[1]


def freeze_annotations(input_path: Path, output: Path, contract_sha256: str, evidence_sha256: str,
                       evidence_kind: str, *, human_declared: bool = False) -> dict:
    """Validate one byte snapshot before writing a new-only frozen package."""
    payload = _read_input(input_path)
    rows, summary = _validate_bytes(payload, contract_sha256, evidence_sha256, evidence_kind, human_declared)
    artifacts = {"imported.csv": payload, "annotations.csv": _csv_bytes(rows), "tasks.json": _tasks_bytes()}
    manifest = dict(summary, schema_version=1, software_version=__version__,
                    module_sha256=file_sha256(Path(__file__)), import_sha256=_hash(payload),
                    artifacts={name: _hash(content) for name, content in artifacts.items()})
    _new_output(output)
    for name, content in artifacts.items():
        _write_new(output / name, content)
    _write_new(output / "manifest.json", _json_bytes(manifest))
    return manifest


def verify_frozen(input_dir: Path, contract_sha256: str, evidence_sha256: str) -> dict:
    """Verify exact membership, hashes and metadata against fixed expected hashes."""
    _check_hashes(contract_sha256, evidence_sha256)
    try:
        paths = list(input_dir.iterdir())
        if {path.name for path in paths} != set(ARTIFACTS) | {"manifest.json"}:
            raise AnnotationError("Frozen package membership does not match the protocol")
        if any(path.is_symlink() or not path.is_file() for path in paths):
            raise AnnotationError("Frozen artifacts must be ordinary files")
        manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
            raise AnnotationError("Unsupported frozen manifest")
        hashes = manifest.get("artifacts")
        if not isinstance(hashes, dict) or set(hashes) != set(ARTIFACTS):
            raise AnnotationError("Frozen artifact hash entries differ from the protocol")
        if any(file_sha256(input_dir / name) != hashes[name] for name in ARTIFACTS):
            raise AnnotationError("Frozen artifact hash mismatch")
        payload = _read_input(input_dir / "imported.csv")
        rows, summary = _validate_bytes(payload, contract_sha256, evidence_sha256,
                                        manifest.get("evidence_kind"), manifest.get("human_declaration"))
        if any(manifest.get(key) != value for key, value in summary.items()):
            raise AnnotationError("Frozen summary differs from the validated records")
        if (manifest.get("import_sha256") != _hash(payload)
                or (input_dir / "annotations.csv").read_bytes() != _csv_bytes(rows)
                or (input_dir / "tasks.json").read_bytes() != _tasks_bytes()):
            raise AnnotationError("Frozen canonical records or protocol differ")
        if manifest.get("module_sha256") != file_sha256(Path(__file__)):
            raise AnnotationError("Frozen validator version differs from the current module")
        return dict(summary, artifact_check="PASS")
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
        raise AnnotationError("Frozen package could not be verified; path and content withheld") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("template", "validate", "freeze", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--contract-sha256", required=True)
        command.add_argument("--evidence-sha256", required=True)
        if name != "template":
            command.add_argument("--input", type=Path, required=True)
        if name in {"template", "freeze"}:
            command.add_argument("--output", type=Path, required=True)
        if name in {"validate", "freeze"}:
            command.add_argument("--evidence-kind", choices=KINDS, required=True)
            command.add_argument("--human-declared", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "template":
            result = prepare_template(args.output, args.contract_sha256, args.evidence_sha256)
        elif args.command == "verify":
            result = verify_frozen(args.input, args.contract_sha256, args.evidence_sha256)
        elif args.command == "validate":
            result = validate_annotations(args.input, args.contract_sha256, args.evidence_sha256,
                                          args.evidence_kind, human_declared=args.human_declared)
        else:
            result = freeze_annotations(args.input, args.output, args.contract_sha256, args.evidence_sha256,
                                        args.evidence_kind, human_declared=args.human_declared)
    except (AnnotationError, OSError) as error:
        print(json.dumps({"gate": "BLOCK", "message": str(error) if isinstance(error, AnnotationError)
                          else "Local I/O failed; path and content withheld"}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
