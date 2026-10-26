"""Conservative presentation projection; never changes scientific input tables.

The conservative profile removes overlapping strata, combinations and research
projections. The explicit synthetic showcase admits bounded overall drug
co-occurrence and exact-comorbidity comparisons from protected change rows.
Annual and longitudinal-change views are synthetic-only because aggregate
marginals cannot establish cross-year or cross-metric complements. This is a
bounded disclosure policy, not anonymization.
"""
from __future__ import annotations

from copy import deepcopy
import math


PROFILE = "conservative-v1"
SHOWCASE_PROFILE = "synthetic-showcase-v1"
DOSE_FIELDS = ("dose_patients", "most_common_dose_values_g", "most_common_dose_patients",
               "most_common_dose_fraction", "most_common_dose_tied")


def _count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return int(number) if math.isfinite(number) and number.is_integer() and number >= 0 else None


def _safe_part(value: object, total: object, threshold: int, allow_zero: bool = False) -> bool:
    part, whole = _count(value), _count(total)
    return (part is not None and whole is not None and whole >= threshold
            and (part >= threshold or (allow_zero and part == 0))
            and part <= whole and (whole - part == 0 or whole - part >= threshold))


def _dose(row: dict, exposed: object, threshold: int) -> dict:
    total, modal = _count(row.get("dose_patients")), _count(row.get("most_common_dose_patients"))
    categories = str(row.get("most_common_dose_values_g", "")).split(";")
    category_count = len(categories) if categories and all(categories) else 0
    valid = (category_count and _safe_part(total, exposed, threshold)
             and _safe_part(modal, total, threshold)
             and modal is not None and total is not None
             and _safe_part(modal * category_count, total, threshold))
    if not valid:
        row.update({key: "" for key in DOSE_FIELDS})
    return row


def _fraction(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 1 else None


def _showcase_combinations(source: dict, protected: dict, threshold: int) -> list[dict]:
    """Admit overall drug co-occurrence using already disclosed item marginals."""
    totals = {row["code"]: row["patients"] for row in protected["groups"]}
    items = {(row["group"], row["item_name"]): row for row in protected["items"]}
    allowed = ("group", "stratum_type", "stratum", "patients", "combination_size", "combination",
               "support_patients", "support", "bootstrap_core_selection_probability", "stable_core_combination")
    rows = []
    seen = set()
    for row in source.get("combinations", []):
        group = row.get("group")
        if (group not in totals or row.get("stratum_type", "overall") != "overall"
                or row.get("stratum", "all") != "all" or "year" in row):
            continue
        members = str(row.get("combination", "")).split(" | ")
        size = _count(row.get("combination_size"))
        support = _count(row.get("support_patients"))
        total = _count(row.get("patients"))
        fraction = _fraction(row.get("support"))
        if (size not in (2, 3) or len(members) != size or len(set(members)) != size
                or any((group, item) not in items for item in members)
                or total != _count(totals[group]) or not _safe_part(support, total, threshold)
                or fraction is None or not math.isclose(fraction, support / total, abs_tol=1e-9)
                or _fraction(row.get("bootstrap_core_selection_probability")) is None
                or str(row.get("stable_core_combination")) not in ("True", "False")):
            continue
        # A disclosed item-minus-co-occurrence count must satisfy the same bound.
        if not all(_safe_part(support, items[group, item]["exposed_patients"], threshold) for item in members):
            continue
        key = (group, tuple(sorted(members)))
        if key not in seen:
            rows.append({key: row[key] for key in allowed if key in row})
            seen.add(key)
    return rows


def _showcase_comparisons(source: dict, protected: dict) -> list[dict]:
    """Rebuild approved member comparisons from both protected change rows.

    The existing patient-equal frequency estimand is retained; missing directions
    are never filled with zero and supplied comparison numbers cannot bypass
    the item-change disclosure projection.
    """
    groups = {row["code"]: row for row in protected["groups"]}
    changes, ambiguous = {}, set()
    for row in protected["changes"]:
        if "year" in row:
            continue
        key = (row["group"], row.get("change_type"), row["item_name"])
        if key in changes:
            ambiguous.add(key)
        changes[key] = row
    rows = []
    seen = set()
    for row in source.get("comparisons", []):
        combination, single = row.get("combination_group"), row.get("single_group")
        if (combination not in groups or single not in groups
                or row.get("stratum_type", "overall") != "overall"
                or row.get("stratum", "all") != "all" or "year" in row):
            continue
        components = combination.split("__")
        if (len(components) < 2 or not all(components) or len(components) != len(set(components))
                or single not in components or "__" in single
                or _count(groups[combination].get("disease_count")) != len(components)
                or _count(groups[single].get("disease_count")) != 1):
            continue
        direction, item = row.get("change_type"), row.get("item_name")
        keys = [(group, direction, item) for group in (combination, single)]
        if direction not in ("addition", "removal") or any(key not in changes or key in ambiguous for key in keys):
            continue
        sides = [changes[key] for key in keys]
        prevalence = [_fraction(side.get("patient_prevalence")) for side in sides]
        frequency = [_fraction(side.get("mean_patient_transition_fraction")) for side in sides]
        if any(p is None or f is None or f > p + 1e-9
               or not math.isclose(p, _count(side["patients_with_change"]) / _count(side["repeat_patients"]), abs_tol=1e-9)
               for side, p, f in zip(sides, prevalence, frequency)):
            continue
        key = (combination, single, direction, item)
        if key in seen:
            continue
        seen.add(key)
        difference = round(frequency[0] - frequency[1], 9)
        clean = {"combination_group": combination, "combination_label": groups[combination]["label"],
                 "single_group": single, "single_label": groups[single]["label"],
                 "stratum_type": "overall", "stratum": "all", "change_type": direction, "item_name": item,
                 "prevalence_difference": round(prevalence[0] - prevalence[1], 9),
                 "mean_transition_fraction_difference": difference,
                 "higher_frequency": "combination" if difference > 0 else "single" if difference < 0 else "equal"}
        for prefix, side in zip(("combination", "single"), sides):
            for field in ("repeat_patients", "patients_with_change", *DOSE_FIELDS):
                clean[f"{prefix}_{field}"] = side.get(field, "")
            clean[f"{prefix}_prevalence"] = side["patient_prevalence"]
            clean[f"{prefix}_mean_transition_fraction"] = side["mean_patient_transition_fraction"]
        rows.append(clean)
    return rows


def protect_payload(payload: dict, min_public_n: int = 10, *, profile: str = PROFILE) -> dict:
    """Return a separate, export-safe fixed projection with no hidden raw rows."""
    if profile not in (PROFILE, SHOWCASE_PROFILE):
        raise ValueError("Unsupported presentation privacy profile")
    if profile == SHOWCASE_PROFILE and payload.get("provenance", {}).get("synthetic_mode") is not True:
        raise ValueError("The showcase profile requires explicit synthetic_mode=True")
    if type(min_public_n) is not int or min_public_n < 10:
        raise ValueError("Presentation threshold must be an integer of at least 10")
    source = deepcopy(payload)
    source_threshold = _count(source.get("provenance", {}).get("min_public_n"))
    previous_threshold = _count(source.get("privacy", {}).get("min_public_n"))
    threshold = max(min_public_n, source_threshold or 10, previous_threshold or 10)
    groups = [{key: row[key] for key in ("code", "label", "patients", "disease_count") if key in row}
              for row in source.get("groups", [])
              if (_count(row.get("patients")) or 0) >= threshold]
    codes = {row["code"] for row in groups}
    totals = {row["code"]: row["patients"] for row in groups}

    def context(row: dict) -> bool:
        return row.get("group") in codes and row.get("stratum_type", "overall") == "overall" and row.get("stratum", "all") == "all"

    year_totals = {(row["group"], str(row["year"])): row.get("patients")
                   for row in source.get("yearSummaries", []) if context(row) and "year" in row}
    repeat_totals = {row["group"]: row.get("repeat_patients")
                     for row in source.get("summaries", []) if context(row)}
    year_repeat_totals = {(row["group"], str(row["year"])): row.get("repeat_patients")
                          for row in source.get("yearSummaries", []) if context(row) and "year" in row}

    def summaries(rows: list) -> list:
        result = []
        for row in rows:
            if not context(row) or (_count(row.get("patients")) or 0) < threshold:
                continue
            if "year" not in row and _count(row["patients"]) != _count(totals[row["group"]]):
                continue
            allowed = ("group", "group_label", "disease_count", "stratum_type", "stratum", "stratum_label", "patients", "year")
            clean = {key: row[key] for key in allowed if key in row}
            clean["repeat_patients"] = row.get("repeat_patients", "") if synthetic and _safe_part(row.get("repeat_patients"), row["patients"], threshold, True) else ""
            result.append(clean)
        return result

    def items(rows: list, change: bool = False) -> list:
        result = []
        numerator, denominator = ("patients_with_change", "repeat_patients") if change else ("exposed_patients", "group_patients")
        allowed = ("group", "stratum_type", "stratum", "item_name", "year", "change_type", numerator, denominator,
                   "patient_prevalence" if change else "prevalence", "mean_patient_transition_fraction", *DOSE_FIELDS)
        for row in rows:
            if not context(row) or not _safe_part(row.get(numerator), row.get(denominator), threshold):
                continue
            source_total = year_totals.get((row["group"], str(row["year"]))) if "year" in row else totals[row["group"]]
            if not change and _count(row.get(denominator)) != _count(source_total):
                continue
            # The same denominator/complement contract applies within each year.
            if change:
                repeat_total = year_repeat_totals.get((row["group"], str(row["year"]))) if "year" in row else repeat_totals.get(row["group"])
                if (_count(row.get(denominator)) != _count(repeat_total)
                        or not _safe_part(row.get(denominator), source_total, threshold)):
                    continue
            result.append(_dose({key: row[key] for key in allowed if key in row}, row[numerator], threshold))
        return result

    synthetic = source.get("provenance", {}).get("synthetic_mode") is True
    provenance_fields = ("project_id", "dataset_id", "cohort_version", "analysis_version", "recorded_run_gate", "artifact_check", "source_sha256", "min_public_n", "synthetic_mode", "config_sha256")
    result = {"version": source.get("version"), "clinicalMode": bool(source.get("clinicalMode")),
              "groups": groups, "summaries": summaries(source.get("summaries", [])),
              "items": items(source.get("items", [])),
              "changes": items(source.get("changes", []), True) if synthetic else [],
              "combinations": [], "comparisons": [], "longitudinal": [],
              "research": {"normalization": [{key: row[key] for key in ("dictionary_version", "dictionary_entries", "dictionary_sha256") if key in row}
                                                for row in source.get("research", {}).get("normalization", [])]},
              "yearSummaries": summaries(source.get("yearSummaries", [])) if synthetic else [],
              "yearItems": items(source.get("yearItems", [])) if synthetic else [],
              "yearChanges": items(source.get("yearChanges", []), True) if synthetic else [],
              "provenance": {key: source.get("provenance", {})[key] for key in provenance_fields if key in source.get("provenance", {})},
              "privacy": {"profile": PROFILE, "min_public_n": threshold, "strata": "overall_only",
                          "requested_min_public_n": min_public_n, "source_min_public_n": source_threshold,
                          "input_presentation_min_public_n": previous_threshold,
                          "annual_policy": "synthetic_only", "annual_enabled": synthetic,
                          "longitudinal_policy": "synthetic_only", "longitudinal_enabled": synthetic,
                          "restricted_projections": ["demographics", "combinations", "comparisons", "networks", "research_inference", "visit_totals"],
                          "guarantee": "bounded_presentation_policy_not_general_anonymization"}}
    if profile == SHOWCASE_PROFILE:
        result["combinations"] = _showcase_combinations(source, result, threshold)
        result["comparisons"] = _showcase_comparisons(source, result)
        result["privacy"].update(
            profile=profile, combinations_enabled=True, comparisons_enabled=True,
            combination_policy="overall_drug_cooccurrence_with_disclosed_item_marginals",
            comorbidity_policy="exact_groups_relative_to_configured_disease_labels",
            synthetic_notice="All patients, assignments, doses and numerical results are synthetic; genuine herb names are vocabulary labels only.",
            restricted_projections=["demographics", "networks", "research_inference", "visit_totals"],
        )
    return result
