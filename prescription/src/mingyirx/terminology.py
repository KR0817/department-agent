"""Prepare public vocabulary for review; compile explicit approvals only."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .dashboard import _read_rows
from .dashboard_research import public_provenance
from .io import file_sha256, normalize_text
from .privacy import SENSITIVE_PATTERNS


class TerminologyError(ValueError):
    """A terminology artifact failed validation; source values are not echoed."""


FIELDS = (
    "source_item_name", "proposed_item_name", "canonical_item_id", "item_type",
    "preparation", "dosage_form", "unit", "review_status", "reviewer_id",
    "evidence_reference",
)
TABLES = (
    "first_prescription_item_prevalence.csv",
    "clinical_first_prescription_item_prevalence.csv",
    "item_normalization_audit.csv",
)


def _safe_cell(value: str) -> str:
    if any(character in value for character in "\r\n\t"):
        raise TerminologyError("Terminology fields must be single-line text")
    value = normalize_text(value)
    if value.startswith(("=", "+", "-", "@")) or any(
        pattern.search(value) for pattern in SENSITIVE_PATTERNS.values()
    ):
        raise TerminologyError("Unsafe terminology field; value withheld")
    return value


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _new_output(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise TerminologyError("Output directory already exists; no files overwritten") from error


def prepare_dictionary(input_dir: Path, output: Path) -> dict[str, object]:
    """Copy only hash-verified, disclosed vocabulary; never infer an approval."""
    try:
        provenance = public_provenance(input_dir, list(TABLES))
    except (ValueError, OSError) as error:
        raise TerminologyError("Aggregate provenance verification failed") from error
    threshold = provenance["min_public_n"]
    if provenance["artifact_check"] != "PASS" or type(threshold) is not int:
        raise TerminologyError("A complete source manifest and privacy threshold are required")
    audit = _read_rows(input_dir / TABLES[2], {"dictionary_entries", "dictionary_version"})
    if len(audit) != 1 or audit[0]["dictionary_entries"] != "0":
        raise TerminologyError("Draft preparation requires an identity-normalized source run")
    names: set[str] = set()
    for table in TABLES[:2]:
        for row in _read_rows(input_dir / table, {"item_name", "exposed_patients", "group_patients"}):
            try:
                exposed, patients = int(row["exposed_patients"]), int(row["group_patients"])
            except ValueError as error:
                raise TerminologyError("Invalid aggregate denominator") from error
            if not threshold <= exposed <= patients:
                raise TerminologyError("Input contains a non-disclosable item row")
            name = _safe_cell(row["item_name"])
            if not name:
                raise TerminologyError("Blank public item name")
            names.add(name)
    if not names:
        raise TerminologyError("No disclosed vocabulary is available")
    rows = []
    for name in sorted(names):
        row = dict.fromkeys(FIELDS, "")
        row.update(source_item_name=name, review_status="pending", item_type="unknown",
                   preparation="unknown", dosage_form="unknown", unit="unknown")
        rows.append(row)
    # Recheck after reading so edits during preparation cannot silently change provenance.
    if public_provenance(input_dir, list(TABLES)) != provenance:
        raise TerminologyError("Aggregate sources changed during preparation")
    _new_output(output)
    review = output / "terminology_review.csv"
    _write_csv(review, FIELDS, rows)
    summary = {
        "gate": "PASS_WITH_WARNINGS", "review_state": "PENDING_HUMAN_REVIEW",
        "vocabulary_scope": "disclosed_first_prescription_items_only",
        "items": len(rows), "approved_mappings": 0, "provenance": provenance,
        "review_sha256": file_sha256(review),
    }
    (output / "review_manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def compile_dictionary(review: Path, version: str, output: Path) -> dict[str, object]:
    """Validate a reviewer ledger and emit the existing loader's exact mapping format."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", version) or version == "source-string-v1":
        raise TerminologyError("A distinct reviewed dictionary version is required")
    original_hash = file_sha256(review)
    with review.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(FIELDS):
            raise TerminologyError("Review columns must match the terminology contract")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise TerminologyError("Malformed review row")
            rows.append({key: _safe_cell(value) for key, value in row.items()})
    by_source: dict[str, dict[str, str]] = {}
    approved = []
    for row in rows:
        source = row["source_item_name"]
        if not source or source in by_source:
            raise TerminologyError("Blank or duplicate normalized source name")
        by_source[source] = row
        if row["review_status"] not in {"pending", "approved", "rejected"}:
            raise TerminologyError("Invalid review status")
        if row["review_status"] != "approved":
            continue
        if any(not value or value.casefold() == "unknown" for value in row.values()):
            raise TerminologyError("Approved rows require complete reviewed metadata")
        if row["item_type"] not in {"herb", "formula", "other_medicine", "other"}:
            raise TerminologyError("Invalid approved item type")
        approved.append(row)
    if not approved:
        raise TerminologyError("No approved mappings; draft cannot be activated")
    names_by_id: dict[str, str] = {}
    metadata_by_name: dict[str, tuple[str, ...]] = {}
    for row in approved:
        target, identifier = row["proposed_item_name"], row["canonical_item_id"]
        metadata = tuple(row[key] for key in ("canonical_item_id", "item_type", "preparation", "dosage_form", "unit"))
        if names_by_id.setdefault(identifier, target) != target:
            raise TerminologyError("Canonical identifier has conflicting names")
        if metadata_by_name.setdefault(target, metadata) != metadata:
            raise TerminologyError("Canonical target has incompatible preparation, form, unit or identity")
        target_row = by_source.get(target)
        if target_row and (target_row["review_status"] != "approved" or target_row["proposed_item_name"] != target):
            raise TerminologyError("Canonical target must be reviewed directly; chains and cycles are invalid")
    if file_sha256(review) != original_hash:
        raise TerminologyError("Review changed during compilation")
    approved.sort(key=lambda row: row["source_item_name"])
    _new_output(output)
    dictionary = output / "item_dictionary.csv"
    _write_csv(dictionary, ("source_item_name", "canonical_item_name"), [
        {"source_item_name": row["source_item_name"], "canonical_item_name": row["proposed_item_name"]}
        for row in approved
    ])
    metadata_path = output / "approved_metadata.csv"
    _write_csv(metadata_path, FIELDS, approved)
    summary = {
        "gate": "PASS_WITH_WARNINGS", "activation": "NOT_APPLIED",
        "approved_mappings": len(approved), "unapproved_rows": len(rows) - len(approved),
        "review_sha256": original_hash, "metadata_sha256": file_sha256(metadata_path),
        "item_normalization": {"version": version, "dictionary_path": dictionary.name,
                               "expected_sha256": file_sha256(dictionary)},
        "required_next_check": "Compare a separately versioned run with the identity baseline",
    }
    (output / "dictionary_manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
