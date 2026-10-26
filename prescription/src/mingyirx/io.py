from __future__ import annotations

import csv
import hashlib
import json
import math
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from .config import AnalysisConfig, ColumnSelector


class InputError(ValueError):
    """Raised when source records cannot satisfy the canonical contract."""


@dataclass(frozen=True)
class LineRecord:
    patient_id: str
    visit_id: str
    visit_date: date
    diagnosis_text: str
    item_name: str
    dose: float | None
    unit: str
    physician_id: str
    sex_source: str = field(default="", compare=False)
    birth_date: date | None = field(default=None, compare=False)
    birth_date_invalid: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class PatientDemographics:
    sex: str | None
    birth_date: date | None


@dataclass(frozen=True)
class SourceFileAudit:
    absolute_path: str
    filename: str
    sha256: str
    bytes: int
    raw_rows: int
    column_count: int
    schema_sha256: str
    duplicate_header_names: tuple[str, ...]


@dataclass(frozen=True)
class ReadResult:
    records: tuple[LineRecord, ...]
    row_count: int
    analysis_row_count: int
    cross_file_overlap_rows_detected: int
    cross_file_overlap_rows_removed: int
    duplicate_line_count: int
    blank_diagnosis_count: int
    unresolved_dose_count: int
    source_files: tuple[SourceFileAudit, ...]
    patient_demographics: dict[str, PatientDemographics]
    demographic_audit: dict[str, int]
    warnings: tuple[str, ...]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.replace("\u3000", " ").split())


def _parse_date(value: str, formats: tuple[str, ...]) -> date:
    for date_format in formats:
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    raise InputError("Unparseable visit date")


def _parse_dose(value: str) -> float | None:
    value = normalize_text(value)
    if not value:
        return None
    try:
        dose = float(value)
    except ValueError:
        return None
    if not math.isfinite(dose) or dose <= 0:
        return None
    return dose


def _schema_sha256(header: tuple[str, ...]) -> str:
    payload = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _resolve_column_indices(
    header: tuple[str, ...], columns: dict[str, ColumnSelector], filename: str
) -> dict[str, int]:
    indices: dict[str, int] = {}
    for canonical_name, selector in columns.items():
        if isinstance(selector, int):
            if selector >= len(header):
                raise InputError(
                    f"{filename}: columns.{canonical_name} position {selector} exceeds "
                    f"the {len(header)}-column source schema"
                )
            indices[canonical_name] = selector
            continue

        matches = [index for index, name in enumerate(header) if name == selector]
        if not matches:
            raise InputError(
                f"{filename}: columns.{canonical_name} header {selector!r} is missing"
            )
        if len(matches) > 1:
            raise InputError(
                f"{filename}: columns.{canonical_name} header {selector!r} is duplicated; "
                "use a zero-based integer position"
            )
        indices[canonical_name] = matches[0]
    return indices


def _expected_digest(config: AnalysisConfig, filename: str) -> str | None:
    matches = [
        digest
        for expected_filename, digest in config.expected_input_sha256.items()
        if expected_filename.casefold() == filename.casefold()
    ]
    return matches[0] if matches else None


def _read_one_source(
    path: Path, config: AnalysisConfig, linkage_values: dict[tuple[str, ...], str]
) -> tuple[list[LineRecord], SourceFileAudit, int, int, tuple[str, ...]]:
    if not path.is_file():
        raise InputError(f"Input file does not exist: {path}")

    digest = file_sha256(path)
    expected_digest = _expected_digest(config, path.name)
    if expected_digest is not None and digest != expected_digest:
        raise InputError(f"{path.name}: SHA-256 does not match the locked configuration")

    records: list[LineRecord] = []
    blank_diagnosis_count = 0
    unresolved_dose_count = 0

    with path.open("r", encoding=config.encoding, newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = tuple(next(reader))
        except StopIteration as error:
            raise InputError(f"{path.name}: input file is empty") from error
        if not header:
            raise InputError(f"{path.name}: source header is empty")
        indices = _resolve_column_indices(header, config.columns, path.name)

        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise InputError(
                    f"{path.name}: row {row_number} has {len(row)} columns; "
                    f"expected {len(header)}"
                )

            def selected(canonical_name: str) -> str:
                index = indices.get(canonical_name)
                return normalize_text(row[index]) if index is not None else ""

            patient_id = selected("patient_id")
            visit_id = selected("visit_id")
            visit_date_text = selected("visit_date")
            diagnosis_text = selected("diagnosis_text")
            item_name = selected("item_name")
            required_values = {
                "patient_id": patient_id,
                "visit_id": visit_id,
                "visit_date": visit_date_text,
                "item_name": item_name,
            }
            missing_values = [key for key, value in required_values.items() if not value]
            if missing_values:
                raise InputError(
                    f"{path.name}: row {row_number} has blank required values: "
                    f"{', '.join(missing_values)}"
                )
            # Normalization may otherwise merge distinct source identities.
            for field_name, key in (
                ("patient_id", ("patient_id", patient_id)),
                ("visit_id", ("visit_id", patient_id, visit_id)),
            ):
                raw_value = row[indices[field_name]]
                if linkage_values.setdefault(key, raw_value) != raw_value:
                    raise InputError(
                        f"Normalization merges distinct {field_name} source values; "
                        "a reviewed linkage mapping is required"
                    )
            if not diagnosis_text:
                blank_diagnosis_count += 1

            dose_text = selected("dose")
            dose = _parse_dose(dose_text)
            if dose_text and dose is None:
                unresolved_dose_count += 1
            try:
                visit_date = _parse_date(visit_date_text, config.date_formats)
            except InputError as error:
                raise InputError(f"{path.name}: row {row_number}: {error}") from error
            birth_date_text = selected("birth_date")
            birth_date: date | None = None
            birth_date_invalid = False
            if birth_date_text:
                try:
                    birth_date = _parse_date(birth_date_text, config.date_formats)
                except InputError:
                    birth_date_invalid = True

            records.append(
                LineRecord(
                    patient_id=patient_id,
                    visit_id=visit_id,
                    visit_date=visit_date,
                    diagnosis_text=diagnosis_text,
                    item_name=item_name,
                    dose=dose,
                    unit=selected("unit"),
                    physician_id=selected("physician_id"),
                    sex_source=selected("sex"),
                    birth_date=birth_date,
                    birth_date_invalid=birth_date_invalid,
                )
            )

    if not records:
        raise InputError(f"{path.name}: input file contains no data rows")

    header_counts = Counter(header)
    audit = SourceFileAudit(
        absolute_path=str(path),
        filename=path.name,
        sha256=digest,
        bytes=path.stat().st_size,
        raw_rows=len(records),
        column_count=len(header),
        schema_sha256=_schema_sha256(header),
        duplicate_header_names=tuple(
            sorted(name for name, count in header_counts.items() if count > 1)
        ),
    )
    return records, audit, blank_diagnosis_count, unresolved_dose_count, header


def _max_multiplicity_records(per_file_records: list[list[LineRecord]]) -> list[LineRecord]:
    order: list[LineRecord] = []
    seen: set[LineRecord] = set()
    maximum_counts: Counter[LineRecord] = Counter()
    for records in per_file_records:
        counts = Counter(records)
        for record in records:
            if record not in seen:
                seen.add(record)
                order.append(record)
        for record, count in counts.items():
            maximum_counts[record] = max(maximum_counts[record], count)

    combined: list[LineRecord] = []
    for record in order:
        combined.extend([record] * maximum_counts[record])
    return combined


def read_sources(paths: Sequence[Path], config: AnalysisConfig) -> ReadResult:
    resolved_paths = tuple(Path(path).resolve() for path in paths)
    if not resolved_paths:
        raise InputError("At least one input file is required")
    if len(set(resolved_paths)) != len(resolved_paths):
        raise InputError("The same input path was supplied more than once")

    supplied_names = {path.name.casefold() for path in resolved_paths}
    expected_names = {name.casefold() for name in config.expected_input_sha256}
    missing_locked_inputs = sorted(expected_names - supplied_names)
    if missing_locked_inputs:
        raise InputError(
            "Locked input files were not supplied: " + ", ".join(missing_locked_inputs)
        )

    per_file_records: list[list[LineRecord]] = []
    audits: list[SourceFileAudit] = []
    blank_diagnosis_count = 0
    unresolved_dose_count = 0
    expected_header: tuple[str, ...] | None = None
    linkage_values: dict[tuple[str, ...], str] = {}
    visit_dates: dict[tuple[str, str], date] = {}
    for path in resolved_paths:
        records, audit, blank_count, unresolved_count, header = _read_one_source(
            path, config, linkage_values
        )
        if expected_header is not None and header != expected_header:
            raise InputError(f"{path.name}: source header schema differs from the first input")
        for record in records:
            key = (record.patient_id, record.visit_id)
            if visit_dates.setdefault(key, record.visit_date) != record.visit_date:
                raise InputError("One visit for one patient has conflicting dates")
        expected_header = header
        per_file_records.append(records)
        audits.append(audit)
        blank_diagnosis_count += blank_count
        unresolved_dose_count += unresolved_count

    raw_row_count = sum(len(records) for records in per_file_records)
    overlap_baseline = _max_multiplicity_records(per_file_records)
    cross_file_overlap_rows_detected = raw_row_count - len(overlap_baseline)
    if config.cross_file_overlap_policy == "max_multiplicity":
        records = overlap_baseline
        cross_file_overlap_rows_removed = cross_file_overlap_rows_detected
    else:
        records = [record for source_records in per_file_records for record in source_records]
        cross_file_overlap_rows_removed = 0

    analysis_row_count = len(records)
    if raw_row_count - cross_file_overlap_rows_removed != analysis_row_count:
        raise InputError("Row-count reconciliation failed")

    duplicate_line_count = sum(count - 1 for count in Counter(records).values() if count > 1)
    patient_sex_values: dict[str, set[str]] = defaultdict(set)
    patient_birth_values: dict[str, set[date]] = defaultdict(set)
    invalid_birth_patients: set[str] = set()
    all_patient_ids: set[str] = set()
    for source_records in per_file_records:
        for record in source_records:
            all_patient_ids.add(record.patient_id)
            if record.sex_source:
                patient_sex_values[record.patient_id].add(
                    record.sex_source.casefold()
                )
            if record.birth_date is not None:
                patient_birth_values[record.patient_id].add(record.birth_date)
            if record.birth_date_invalid:
                invalid_birth_patients.add(record.patient_id)

    patient_demographics: dict[str, PatientDemographics] = {}
    audit_counts = Counter()
    sex_mapping = config.clinical_phenotype_analysis.sex_value_to_category
    for patient_id in all_patient_ids:
        sex_values = patient_sex_values[patient_id]
        if len(sex_values) == 1:
            sex = sex_mapping.get(next(iter(sex_values)))
            if sex is None:
                audit_counts["sex_unmapped_patients"] += 1
        else:
            sex = None
            audit_counts[
                "sex_missing_patients" if not sex_values else "sex_inconsistent_patients"
            ] += 1

        birth_values = patient_birth_values[patient_id]
        if patient_id in invalid_birth_patients:
            birth_date = None
            audit_counts["birth_unparseable_patients"] += 1
        elif len(birth_values) == 1:
            birth_date = next(iter(birth_values))
        else:
            birth_date = None
            audit_counts[
                "birth_missing_patients" if not birth_values else "birth_inconsistent_patients"
            ] += 1
        patient_demographics[patient_id] = PatientDemographics(
            sex=sex,
            birth_date=birth_date,
        )

    warnings: list[str] = []
    if cross_file_overlap_rows_detected:
        action = (
            "removed by max_multiplicity policy"
            if cross_file_overlap_rows_removed
            else "retained by append policy"
        )
        warnings.append(
            f"{cross_file_overlap_rows_detected} exact cross-file overlap rows were {action}"
        )
    if duplicate_line_count:
        warnings.append(f"{duplicate_line_count} exact duplicate item lines collapse within visits")
    if blank_diagnosis_count:
        warnings.append(f"{blank_diagnosis_count} item lines have blank diagnosis text")
    if unresolved_dose_count:
        warnings.append(
            f"{unresolved_dose_count} nonblank dose values could not be parsed as positive numbers"
        )
    if config.clinical_phenotype_analysis.enabled and any(
        audit_counts[key]
        for key in (
            "sex_missing_patients",
            "sex_inconsistent_patients",
            "sex_unmapped_patients",
        )
    ):
        warnings.append(
            "Some patients have missing, inconsistent, or unmapped sex values and remain unknown"
        )
    if config.clinical_phenotype_analysis.enabled and any(
        audit_counts[key]
        for key in (
            "birth_missing_patients",
            "birth_inconsistent_patients",
            "birth_unparseable_patients",
        )
    ):
        warnings.append(
            "Some patients have missing, inconsistent, or unparseable birth dates and remain unknown"
        )

    return ReadResult(
        records=tuple(records),
        row_count=raw_row_count,
        analysis_row_count=analysis_row_count,
        cross_file_overlap_rows_detected=cross_file_overlap_rows_detected,
        cross_file_overlap_rows_removed=cross_file_overlap_rows_removed,
        duplicate_line_count=duplicate_line_count,
        blank_diagnosis_count=blank_diagnosis_count,
        unresolved_dose_count=unresolved_dose_count,
        source_files=tuple(audits),
        patient_demographics=patient_demographics,
        demographic_audit=dict(audit_counts),
        warnings=tuple(warnings),
    )


def read_source(path: Path, config: AnalysisConfig) -> ReadResult:
    """Backward-compatible single-file wrapper."""
    return read_sources((path,), config)
