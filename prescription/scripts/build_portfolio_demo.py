"""Build a deterministic local-only outpatient demo from generated synthetic rows."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mingyirx.dashboard import build_dashboard
from mingyirx.dashboard_sources import build_source_dashboard
from mingyirx.pipeline import run_pipeline
from mingyirx.terminology import prepare_dictionary

VERSION = "multidisease-showcase-20261023-v1"
POLICY = "synthetic-showcase-v1"
VOCABULARY = ROOT / "configs/showcase_vocabulary.json"
DISEASES = [
    ("ra", "RA", "Rheumatoid arthritis"),
    ("sjd", "SjD", "Sjogren disease"),
    ("as", "AS", "Ankylosing spondylitis"),
    ("sle", "SLE", "Systemic lupus erythematosus"),
    ("oa", "OA", "Osteoarthritis"),
    ("gout", "GOUT", "Gout"),
]
PHENOTYPES = [
    ("ra", 120, 80), ("sjd", 100, 60), ("as", 100, 80),
    ("sle", 80, 60), ("oa", 120, 80), ("gout", 100, 60),
    ("ra__sjd", 80, 60), ("sjd__sle", 60, 40), ("ra__oa", 60, 40),
    ("as__oa", 60, 40), ("oa__gout", 60, 40), ("ra__sjd__oa", 40, 40),
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def source_fixture(directory: Path, source: str) -> tuple[Path, Path]:
    """No real input path is accepted: fixture generation is the only data source."""
    directory.mkdir(parents=True)
    groups = {code: primary if source == "primary" else supplement for code, primary, supplement in PHENOTYPES}
    years = [2022, 2023, 2024, 2025] if source == "primary" else [2023, 2024, 2025, 2026]
    diagnoses = {code: token for code, token, _ in DISEASES}
    vocabulary = json.loads(VOCABULARY.read_text(encoding="utf-8"))
    source_offset = 0 if source == "primary" else 2
    rows = []
    for group_index, (group, count) in enumerate(groups.items()):
        blocks = count // 10
        for index in range(count):
            patient = f"SYNTH_{source}_{group}_{index:03d}"
            block = index // 10
            for step, year in enumerate(years):
                items = []
                for item_index, item in enumerate(vocabulary["items"]):
                    # Ten-person blocks exercise thresholds without real clinical relationships.
                    if item_index < 2:
                        present = True
                    elif item_index == 2:
                        present = block < blocks - 1
                    else:
                        covered = 2 + (item_index + group_index + source_offset) % max(1, blocks - 3)
                        shift = 1 + (group_index + group_index // 3 + source_offset + item_index) % 3
                        rank = (block + item_index * 3 + group_index + source_offset + step * shift) % blocks
                        present = rank < covered
                    if present:
                        dose = "" if item["synthetic_recorded_grams"] is None else str(item["synthetic_recorded_grams"])
                        if item_index == 0:
                            dose = "10" if index < count // 2 else "15"
                        items.append((item["name"], dose))
                for item, dose in items:
                    rows.append({"patient_id": patient, "visit_id": f"SYNTH_V{step:02d}",
                                 "visit_date": f"{year}-06-15", "diagnosis_text": " / ".join(diagnoses[code] for code in group.split("__")),
                                 "item_name": item, "dose": dose, "unit": "g", "physician_id": "SYNTH_DOCTOR",
                                 "sex": "F" if index % 2 else "M", "birth_date": "1980-01-01"})
    fields = list(rows[0])
    rows.append(dict(rows[0]))
    input_path = directory / "synthetic_prescriptions.csv"
    write_csv(input_path, fields, rows)
    dictionary = directory / "synthetic_dictionary.csv"
    write_csv(dictionary, ["source_item_name", "canonical_item_name"],
              [{"source_item_name": item["name"], "canonical_item_name": item["name"]} for item in vocabulary["items"]])
    config = json.loads((ROOT / "configs/example.json").read_text(encoding="utf-8"))
    config.update({"project_id": "MINGYIRX_PORTFOLIO_SYNTHETIC", "dataset_id": f"SYNTHETIC_{source.upper()}_V2",
                   "cohort_version": VERSION, "synthetic_mode": True, "min_public_n": 10,
                   "early_end_year": 2024, "temporal_cutpoints": [2024],
                   "core_prevalence": 0.5, "require_visit_group_match": True})
    config["columns"].update({"sex": "sex", "birth_date": "birth_date"})
    config["groups"] = [{"name": code, "label": label, "include_patterns": [rf"\b{token}\b"], "exclude_patterns": []}
                        for code, token, label in DISEASES]
    config["item_normalization"] = {"version": vocabulary["version"], "dictionary_path": dictionary.name,
                                    "expected_sha256": digest(dictionary)}
    config["matched_reference"]["enabled"] = False
    config["combination_analysis"]["enabled"] = True
    config["network_analysis"]["enabled"] = False
    config["clinical_phenotype_analysis"] = {"enabled": True, "other_exclude_patterns": [],
        "sex_categories": [{"name": "female", "label": "Female", "source_values": ["F"]},
                           {"name": "male", "label": "Male", "source_values": ["M"]}],
        "age_bands": [{"name": "adult", "label": "Adult", "min_age": 18, "max_age": 64}]}
    config_path = directory / "synthetic_config.json"
    write_json(config_path, config)
    write_json(directory / "fixture_provenance.json", {"version": VERSION, "synthetic": True,
        "real_patient_records": 0, "source": source, "source_within_patients": sum(groups.values()),
        "groups": groups, "years": years, "duplicate_lines_added": 1,
        "generator_sha256": digest(Path(__file__)), "input_sha256": digest(input_path),
        "dictionary_sha256": digest(dictionary), "config_sha256": digest(config_path),
        "vocabulary_sha256": digest(VOCABULARY), "diseases": 6, "exact_phenotypes": len(groups),
        "terminology_status": "Real herb labels verified for name existence only; all assignments and doses synthetic"})
    return config_path, input_path


def deterministic_zip(directory: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(path.relative_to(directory).as_posix(), (2026, 10, 22, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())


def build(output: Path) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    public = output / "public"
    public.mkdir()
    results = {}
    metadata = {
        "primary": {"title": "\u5408\u6210\u4e3b\u8981\u95e8\u8bca\u6765\u6e90",
                    "scope": "980\u540d\u5408\u6210\u60a3\u8005\uff0c6\u4e2a\u5355\u75c5\u7ec4\u4e0e6\u4e2a\u5171\u75c5\u7ec4\uff0c2022\u20142025\u5e74\u3002\u836f\u540d\u771f\u5b9e\uff1b\u5904\u65b9\u3001\u514b\u6570\u548c\u7edf\u8ba1\u7ed3\u679c\u5747\u4e3a\u5408\u6210\u3002"},
        "supplement": {"title": "\u5408\u6210\u8865\u5145\u95e8\u8bca\u6765\u6e90",
                       "scope": "680\u540d\u5408\u6210\u60a3\u8005\uff0c6\u4e2a\u5355\u75c5\u7ec4\u4e0e6\u4e2a\u5171\u75c5\u7ec4\uff0c2023\u20142026\u5e74\u3002\u6765\u6e90\u72ec\u7acb\u5c55\u793a\uff0c\u4eba\u6570\u4e0d\u76f8\u52a0\u3002"},
    }
    pages = {}
    for source in ("primary", "supplement"):
        development = output / "development" / source
        config_path, input_path = source_fixture(development, source)
        aggregates = development / "aggregates"
        manifest = run_pipeline(config_path, input_path, aggregates)
        page = development / "dashboard.html"
        build_dashboard(aggregates, page, metadata[source]["title"], privacy_policy=POLICY, min_public_n=10)
        pages[source] = page
        results[source] = {"pipeline_gate": manifest["gate"], "artifact_hashes": manifest["artifacts"],
                           "input_sha256": digest(input_path), "config_sha256": digest(config_path)}
    summary = build_source_dashboard(pages["primary"], pages["supplement"], public / "index.html",
        privacy_policy=POLICY, min_public_n=10, source_metadata=metadata, default_source="primary")
    primary_dev = output / "development" / "primary"
    identity_config = json.loads((primary_dev / "synthetic_config.json").read_text(encoding="utf-8"))
    identity_config["item_normalization"] = {"version": "source-string-v1", "dictionary_path": None,
                                               "expected_sha256": None}
    identity_path = primary_dev / "synthetic_identity_config.json"
    write_json(identity_path, identity_config)
    run_pipeline(identity_path, primary_dev / "synthetic_prescriptions.csv", primary_dev / "identity_aggregates")
    terminology = prepare_dictionary(primary_dev / "identity_aggregates", output / "terminology_pending")
    (public / "README.txt").write_text(
        "MingYiRx multidisease and comorbidity demo\nReal herb names; all patient records, assignments, counts and doses are generated development examples.\n"
        "Open index.html in a browser, or run: python -m http.server 8765 --bind 127.0.0.1\n"
        "The server directory must be this public folder only. No network request is needed.\n"
        "Sources remain separate. Dose means a recorded per-item value, not a daily dose or recommendation.\n"
        "No clinical accuracy, usability, safety or efficacy validation is claimed.\n", encoding="utf-8")
    document = (public / "index.html").read_text(encoding="utf-8")
    if any(term in document for term in ("SYNTH_primary_", "SYNTH_supplement_", "patient_id", "visit_id", "birth_date")):
        raise ValueError("Patient-level fixture keys leaked into public demo")
    if re.search(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b", document):
        raise ValueError("Exact dates leaked into public demo")
    deterministic_zip(public, output / "mingyirx-local-demo.zip")
    record = {"version": VERSION, "privacy_policy": POLICY, "synthetic": True,
              "public_release": False, "historical_scientific_results_recomputed": False,
              "source_builds": results, "dashboard": summary,
              "terminology_pending": {"items": terminology["items"], "approved_mappings": 0,
                                      "review_sha256": terminology["review_sha256"],
                                      "synthetic_assignments_only": True,
                                      "real_herb_names": True},
              "vocabulary": {"sha256": digest(VOCABULARY), "name_source": json.loads(VOCABULARY.read_text(encoding="utf-8"))["source"],
                             "items": 18, "scope": "name_existence_only"},
              "public_hashes": {p.name: digest(p) for p in sorted(public.iterdir())},
              "zip_sha256": digest(output / "mingyirx-local-demo.zip")}
    write_json(output / "build_manifest.json", record)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New destination; overwrite is refused")
    args = parser.parse_args()
    result = build(args.output)
    print(json.dumps({"version": result["version"], "zip_sha256": result["zip_sha256"],
                      "synthetic": True, "public_release": False}))
