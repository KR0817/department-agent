"""Carry-forward software benchmark for explicitly synthetic visit histories."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path


SCHEMA_VERSION = 1
MAX_INPUT_BYTES = 1024 * 1024
UNITS = {"g", "G", "mg", "mL", "tablet", "unknown"}


class BenchmarkError(ValueError):
    """The synthetic development fixture violates the fixed contract."""


def _keys(value: object, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise BenchmarkError("Unexpected fixture fields; source values withheld")


def _integer(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _dose(item: dict) -> tuple[tuple[float, str] | None, str]:
    values = {(row["value"], row["unit"]) for row in item["dose_pairs"]
              if row["value"] is not None and row["value"] > 0}
    if len(values) > 1:
        return None, "conflict"
    if not values:
        return None, "missing"
    value, unit = next(iter(values))
    return (float(value), unit), "resolved"


def validate_fixture(fixture: object) -> dict:
    """Accept only coded synthetic histories, never a clinical input manifest."""
    _keys(fixture, {"schema_version", "synthetic_mode", "periods", "patients"})
    if type(fixture["schema_version"]) is not int or fixture["schema_version"] != SCHEMA_VERSION:
        raise BenchmarkError("Unsupported fixture version")
    if fixture["synthetic_mode"] is not True:
        raise BenchmarkError("Only explicitly synthetic development fixtures are accepted")
    periods = fixture["periods"]
    if (not isinstance(periods, list) or not 1 <= len(periods) <= 20
            or any(not isinstance(p, str) or not re.fullmatch(r"period_[1-9][0-9]?", p) for p in periods)
            or len(set(periods)) != len(periods)):
        raise BenchmarkError("Periods must be distinct fixed synthetic period codes")
    patients = fixture["patients"]
    if not isinstance(patients, list) or not 1 <= len(patients) <= 1000:
        raise BenchmarkError("A bounded nonempty synthetic patient list is required")
    seen = set()
    for patient in patients:
        _keys(patient, {"patient_code", "visits"})
        code = patient["patient_code"]
        if not isinstance(code, str) or not re.fullmatch(r"SYN-P-[0-9]{4}", code) or code in seen:
            raise BenchmarkError("Patient codes must be unique synthetic codes")
        seen.add(code)
        visits = patient["visits"]
        if not isinstance(visits, list) or not 1 <= len(visits) <= 1000:
            raise BenchmarkError("A bounded nonempty visit history is required")
        last_day, last_period = -1, -1
        for index, visit in enumerate(visits, start=1):
            _keys(visit, {"sequence", "day_offset", "period", "eligible", "items"})
            if not _integer(visit["sequence"], 1, 1000) or visit["sequence"] != index:
                raise BenchmarkError("Original visit sequences must be complete and ordered")
            if not _integer(visit["day_offset"], 0, 36500) or visit["day_offset"] < last_day:
                raise BenchmarkError("Synthetic day offsets must be nonnegative and ordered")
            if not isinstance(visit["period"], str) or visit["period"] not in periods:
                raise BenchmarkError("Visit period is not in the fixed period definition")
            period_index = periods.index(visit["period"])
            if period_index < last_period or type(visit["eligible"]) is not bool:
                raise BenchmarkError("Period ordering or visit eligibility is invalid")
            last_day, last_period = visit["day_offset"], period_index
            items = visit["items"]
            if not isinstance(items, list) or len(items) > 100 or (visit["eligible"] and not items):
                raise BenchmarkError("Eligible prescriptions require nonempty bounded item sets")
            names = set()
            for item in items:
                _keys(item, {"item_name", "dose_pairs"})
                name = item["item_name"]
                if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z\u3400-\u9fff][A-Za-z0-9 _\u3400-\u9fff-]{0,31}", name)
                        or name != name.strip() or name in names):
                    raise BenchmarkError("Duplicate or invalid synthetic medication label")
                names.add(name)
                pairs = item["dose_pairs"]
                if not isinstance(pairs, list) or len(pairs) > 10:
                    raise BenchmarkError("Dose pairs must be a bounded list")
                for dose in pairs:
                    _keys(dose, {"value", "unit"})
                    value, unit = dose["value"], dose["unit"]
                    if (value is not None and (type(value) not in (int, float) or not -1e12 <= value <= 1e12 or not math.isfinite(value))
                            or not isinstance(unit, str) or unit not in UNITS):
                        raise BenchmarkError("Invalid recorded dose or unit; values withheld")
    return fixture


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _pair(patient: str, previous: dict, current: dict) -> dict:
    prior = {item["item_name"]: item for item in previous["items"]}
    actual = {item["item_name"]: item for item in current["items"]}
    retained = prior.keys() & actual.keys()
    added, removed = actual.keys() - prior.keys(), prior.keys() - actual.keys()
    dose_rows = []
    for name in sorted(retained):
        before, before_status = _dose(prior[name])
        after, after_status = _dose(actual[name])
        reason = ("conflict" if "conflict" in {before_status, after_status} else
                  "missing" if before is None or after is None else
                  "incompatible_unit" if before[1].casefold() != "g" or after[1].casefold() != "g" else
                  "comparable")
        delta = after[0] - before[0] if reason == "comparable" else None
        direction = (None if delta is None else "unchanged" if math.isclose(delta, 0, abs_tol=1e-12)
                     else "increase" if delta > 0 else "decrease")
        dose_rows.append({"item_name": name, "status": reason, "observed_delta_g": delta,
                          "observed_direction": direction,
                          "predicted_delta_g": 0.0 if delta is not None else None,
                          "absolute_error_g": abs(delta) if delta is not None else None})
    changed_doses = [row for row in dose_rows if row["observed_direction"] in {"increase", "decrease"}]
    comparable = [row for row in dose_rows if row["status"] == "comparable"]
    return {
        "patient_code": patient, "prior_sequence": previous["sequence"], "current_sequence": current["sequence"],
        "gap_days": current["day_offset"] - previous["day_offset"], "period": current["period"],
        "added": sorted(added), "removed": sorted(removed), "retained": sorted(retained),
        "predicted_added": [], "predicted_removed": [],
        "contextual_set_jaccard": len(retained) / len(prior.keys() | actual.keys()),
        "addition_precision": None, "addition_recall": 0.0 if added else None,
        "removal_precision": None, "removal_recall": 0.0 if removed else None,
        "composition_no_change": not added and not removed,
        "fully_resolved_no_change": (False if added or removed or changed_doses else
                                     True if len(comparable) == len(retained) else None),
        "dose_comparisons": dose_rows, "comparable_retained_items": len(comparable),
        "dose_change_precision": None, "dose_change_recall": 0.0 if changed_doses else None,
        "dose_change_events": len(changed_doses),
    }


def _summary(rows: list[dict]) -> dict:
    patients = sorted({row["patient_code"] for row in rows})
    jaccards = [_mean([row["contextual_set_jaccard"] for row in rows if row["patient_code"] == patient]) for patient in patients]
    dose_rows = [dose for row in rows for dose in row["dose_comparisons"]]
    comparable = [dose for dose in dose_rows if dose["status"] == "comparable"]
    patient_dose_errors = []
    for patient in patients:
        errors = [dose["absolute_error_g"] for row in rows if row["patient_code"] == patient
                  for dose in row["dose_comparisons"] if dose["absolute_error_g"] is not None]
        if errors:
            patient_dose_errors.append(statistics.fmean(errors))
    added = sum(len(row["added"]) for row in rows)
    removed = sum(len(row["removed"]) for row in rows)
    dose_changes = sum(row["dose_change_events"] for row in rows)
    return {
        "patients": len(patients), "pairs": len(rows), "added_events": added, "removed_events": removed,
        "retained_events": len(dose_rows), "composition_no_change_pairs": sum(row["composition_no_change"] for row in rows),
        "fully_resolved_no_change_pairs": sum(row["fully_resolved_no_change"] is True for row in rows),
        "unresolved_no_change_status_pairs": sum(row["fully_resolved_no_change"] is None for row in rows),
        "patient_equal_contextual_set_jaccard": _mean(jaccards),
        "addition_precision": None, "addition_recall": 0.0 if added else None,
        "removal_precision": None, "removal_recall": 0.0 if removed else None,
        "change_event_recall": 0.0 if added + removed else None,
        "dose_comparable_events": len(comparable),
        "dose_coverage": len(comparable) / len(dose_rows) if dose_rows else None,
        "dose_unresolved": {reason: sum(row["status"] == reason for row in dose_rows)
                            for reason in ("missing", "conflict", "incompatible_unit")},
        "dose_change_events": dose_changes, "dose_change_precision": None,
        "dose_change_recall": 0.0 if dose_changes else None,
        "dose_direction_accuracy": (sum(row["observed_direction"] == "unchanged" for row in comparable) / len(comparable)
                                    if comparable else None),
        "patient_equal_dose_mae_g": _mean(patient_dose_errors),
    }


def evaluate_fixture(fixture: object) -> dict:
    """Keep original adjacency, excluding every ambiguous-day incident pair.

    This conservative synthetic benchmark rule does not replace the legacy
    analysis's deterministic same-day ordering or its released estimands.
    """
    fixture = validate_fixture(fixture)
    rows, skipped = [], {"same_day": 0, "ambiguous_day_endpoint": 0, "ineligible_endpoint": 0}
    original_adjacencies = 0
    for patient in fixture["patients"]:
        visits = patient["visits"]
        day_counts = Counter(visit["day_offset"] for visit in visits)
        for previous, current in zip(visits, visits[1:]):
            original_adjacencies += 1
            if not previous["eligible"] or not current["eligible"]:
                skipped["ineligible_endpoint"] += 1
            elif current["day_offset"] == previous["day_offset"]:
                skipped["same_day"] += 1
            elif day_counts[previous["day_offset"]] > 1 or day_counts[current["day_offset"]] > 1:
                skipped["ambiguous_day_endpoint"] += 1
            else:
                rows.append(_pair(patient["patient_code"], previous, current))
    return {"gate": "PASS", "schema_version": SCHEMA_VERSION,
            "evidence_state": "SYNTHETIC_SOFTWARE_CHECK_ONLY", "clinical_evidence": False,
            "baseline": "copy_previous_prescription", "learned_model_evaluated": False,
            "scope": "Synthetic carry-forward behavior; no clinical prediction or temporal-stability claim",
            "original_adjacencies": original_adjacencies,
            "same_day_policy": "Exclude same-day pairs and every original edge touching an ambiguously ordered day; never reconnect",
            "skipped_original_adjacencies": skipped, "summary": _summary(rows),
            "periods": [{"period": period, **_summary([row for row in rows if row["period"] == period])}
                        for period in fixture["periods"]], "pairs": rows}


def _reject_constant(value: str) -> None:
    raise BenchmarkError("Nonfinite JSON values are not accepted")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkError("Duplicate JSON fields are not accepted")
        result[key] = value
    return result


def run(input_path: Path, output: Path | None = None) -> dict:
    if input_path.suffix.lower() != ".json":
        raise BenchmarkError("A synthetic JSON fixture is required")
    with input_path.open("rb") as handle:
        payload = handle.read(MAX_INPUT_BYTES + 1)
    if len(payload) > MAX_INPUT_BYTES:
        raise BenchmarkError("Fixture exceeds the one-megabyte limit")
    try:
        fixture = json.loads(payload.decode("utf-8"), parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BenchmarkError("Invalid fixture JSON; content withheld") from error
    result = evaluate_fixture(fixture)
    result["input_sha256"] = hashlib.sha256(payload).hexdigest()
    if output is not None:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=True, allow_nan=False)
            handle.write("\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.input, args.output)
    except (BenchmarkError, OSError) as error:
        print(json.dumps({"gate": "BLOCK", "message": str(error) if isinstance(error, BenchmarkError)
                          else "Local I/O failed; path and content withheld"}))
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
