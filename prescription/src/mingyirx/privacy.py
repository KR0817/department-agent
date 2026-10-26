from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


FORBIDDEN_PUBLIC_HEADERS = {
    "patient_id",
    "visit_id",
    "visit_date",
    "diagnosis_text",
    "patient_name",
    "name",
    "phone",
    "telephone",
    "address",
    "id_card",
    "medical_record_number",
}

SENSITIVE_PATTERNS = {
    "mainland_mobile_phone": re.compile(r"(?<![\d.])1[3-9]\d{9}(?!\d)"),
    "mainland_identity_number": re.compile(r"(?<![\d.])\d{17}[\dXx](?![\dXx])"),
}


@dataclass(frozen=True)
class PrivacyScan:
    files_scanned: int
    issues: tuple[str, ...]


def scan_public_outputs(output_dir: Path) -> PrivacyScan:
    issues: list[str] = []
    files = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file()
        and path.name != "run_manifest.json"
        and path.suffix.lower() in {".csv", ".md", ".json"}
    )
    for path in files:
        text = path.read_text(encoding="utf-8")
        for pattern_name, pattern in SENSITIVE_PATTERNS.items():
            if pattern.search(text):
                issues.append(f"{path.name}: possible {pattern_name}")
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                headers = {header.strip().casefold() for header in next(reader, [])}
            forbidden = sorted(headers & FORBIDDEN_PUBLIC_HEADERS)
            if forbidden:
                issues.append(f"{path.name}: forbidden public headers {', '.join(forbidden)}")
    return PrivacyScan(files_scanned=len(files), issues=tuple(issues))
