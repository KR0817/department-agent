"""Build explicitly simulated cases anchored to disclosed aggregate triples."""
from __future__ import annotations

from copy import deepcopy
import math
import re

from .inheritance import InheritanceError, template_bundle, validate_bundle
from .reviewed_dashboard import payload_hash, validate_payload


class AggregateTeachingError(InheritanceError):
    """A coded aggregate-boundary failure without submitted values."""


_COMBINATION_KEYS = {
    "group", "stratum_type", "stratum", "patients", "combination_size",
    "combination", "support_patients", "support",
    "bootstrap_core_selection_probability", "stable_core_combination",
}
_TARGETS = (
    ("primary", "ra_strict", "RA"),
    ("primary", "sjd_strict", "SJD"),
    ("primary", "as_strict", "AS"),
    ("primary", "ra_strict__sjd_strict", "RA_SJD"),
    ("supplement", "as_strict", "AS"),
)
_CONDITIONS = {
    "RA": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u7c7b\u98ce\u6e7f\u5173\u8282\u708e",
    "SJD": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u5e72\u71e5\u7efc\u5408\u5f81",
    "AS": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u5f3a\u76f4\u6027\u810a\u67f1\u708e",
}
_PROFILES = {
    "RA": (("RA",), ("PAIN", "FATIGUE"), "DAMP_HEAT", "CLEAR_HEAT"),
    "SJD": (("SJD",), ("DRY_MOUTH", "FATIGUE"), "DRY_DAMP", "MOISTEN"),
    "AS": (("AS",), ("STIFFNESS", "COLD"), "KIDNEY_COLD", "SUPPORT_DU"),
    "RA_SJD": (("RA", "SJD"), ("PAIN", "DRY_MOUTH"), "DRY_DAMP_PAIN", "MOISTEN"),
}
_VOCABULARY = {
    "symptoms": {
        "PAIN": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u5173\u8282\u75bc\u75db",
        "FATIGUE": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u4e4f\u529b",
        "DRY_MOUTH": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u53e3\u5e72",
        "STIFFNESS": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u8170\u80cc\u50f5\u786c",
        "COLD": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u754f\u5bd2",
    },
    "tongues": {
        "THICK": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u82d4\u539a\u817b",
        "THIN": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u82d4\u8584",
    },
    "pulses": {"WIRY": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u8109\u5f26"},
    "syndromes": {
        "DAMP_HEAT": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u6e7f\u70ed\u75f9\u963b",
        "DRY_DAMP": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u71e5\u6e7f\u4e92\u7ed3",
        "KIDNEY_COLD": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u80be\u865a\u7763\u5bd2",
        "DRY_DAMP_PAIN": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u71e5\u6e7f\u4e92\u7ed3\u517c\u75f9\u963b",
    },
    "principles": {
        "CLEAR_HEAT": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u6e05\u70ed\u901a\u7edc",
        "MOISTEN": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u5316\u6e7f\u6da6\u71e5",
        "SUPPORT_DU": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u8865\u80be\u5f3a\u7763",
    },
    "contexts": {
        "PARTIAL_COMBINATION": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u4e09\u836f\u7ec4\u5408\u5c40\u90e8\u7ec3\u4e60\uff0c\u975e\u5b8c\u6574\u539f\u65b9",
    },
    "outcomes": {
        "NO_REAL_OUTCOME": "\u6559\u5b66\u8bbe\u5b9a\uff1a\u65e0\u771f\u5b9e\u540e\u7eed\u7ed3\u5c40",
    },
}
_SIMULATED_FIELDS = [
    "case_id", "subject_id", "physician_id", "source_id", "condition_codes",
    "visits[*].visit_id", "visits[*].sequence", "visits[*].offset_days",
    "visits[*].order_known", "visits[*].pre.symptoms",
    "visits[*].pre.tongue_codes", "visits[*].pre.pulse_codes",
    "visits[*].pre.syndrome_codes", "visits[*].pre.principle_codes",
    "visits[*].pre.context_codes", "visits[*].prescription.membership",
    "visits[*].prescription[*].dose", "visits[*].prescription[*].unit",
    "visits[*].prescription[*].basis", "visits[*].prescription[*].formulation",
    "visits[*].prescription[*].preparation", "visits[*].outcome_codes",
    "annotations[*].statement", "annotations[*].author_id",
    "annotations[*].origin", "annotations[*].status",
    "physician_and_source_attribution", "adjacent_visit_drug_changes",
]


def _count(value: object) -> int | None:
    if value is None or value == "":
        return None
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{1,12}", value, flags=re.ASCII):
        return int(value)
    raise AggregateTeachingError("AGGREGATE_COUNT_INVALID")


def _probability(value: object) -> float:
    try:
        if type(value) not in (int, float, str):
            raise ValueError
        result = float(value)
        if not math.isfinite(result) or not 0 <= result <= 1:
            raise ValueError
        return result
    except (ValueError, TypeError, OverflowError):
        raise AggregateTeachingError("AGGREGATE_PROBABILITY_INVALID") from None


def _select(payload: dict, group: str) -> tuple[int, dict, list[str]] | None:
    """Select a disclosed overall triple without combining unrelated marginals."""
    threshold = payload["provenance"]["min_public_n"]
    groups = [row for row in payload["groups"] if row.get("code", row.get("group")) == group]
    if len(groups) > 1:
        raise AggregateTeachingError("AGGREGATE_GROUP_DUPLICATE")
    if not groups:
        return None
    denominator = _count(groups[0].get("patients"))
    if denominator is None or denominator < threshold:
        return None
    candidates = []
    for index, row in enumerate(payload["combinations"]):
        if (row.get("group"), row.get("stratum_type"), row.get("stratum")) != (group, "overall", "all"):
            continue
        size = _count(row.get("combination_size"))
        if size == 2:
            continue
        if size != 3 or not _COMBINATION_KEYS <= row.keys():
            raise AggregateTeachingError("AGGREGATE_COMBINATION_INVALID")
        support = _count(row["support_patients"])
        patients = _count(row["patients"])
        if support is None or support < threshold or patients is None:
            continue
        if patients != denominator or support > patients:
            raise AggregateTeachingError("AGGREGATE_DENOMINATOR_MISMATCH")
        probability = _probability(row["support"])
        if abs(probability - support / patients) > 1e-8:
            raise AggregateTeachingError("AGGREGATE_SUPPORT_MISMATCH")
        _probability(row["bootstrap_core_selection_probability"])
        core_flag = row["stable_core_combination"]
        if not (type(core_flag) is bool or type(core_flag) is str and core_flag in ("True", "False")):
            raise AggregateTeachingError("AGGREGATE_CORE_FLAG_INVALID")
        if not isinstance(row["combination"], str):
            raise AggregateTeachingError("AGGREGATE_COMBINATION_INVALID")
        names = [name.strip() for name in row["combination"].split("|")]
        if len(names) != 3 or len(set(names)) != 3 or any(not name or len(name) > 80 for name in names):
            raise AggregateTeachingError("AGGREGATE_COMBINATION_INVALID")
        candidates.append((index, row, names))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (-_count(item[1]["support_patients"]), item[1]["combination"], item[0]))


def _visit(number: int, names: list[str], medicines: dict[str, str], profile: str) -> dict:
    _, symptoms, syndrome, principle = _PROFILES[profile]
    selected = names if number != 2 else names[:2]
    return {
        "visit_id": "SIM_VISIT_" + str(number), "sequence": number,
        "offset_days": (number - 1) * 14, "order_known": True,
        "pre": {
            "symptoms": [{"code": "SIM_" + code, "severity": 1 if number == 2 else 2} for code in symptoms],
            "tongue_codes": ["SIM_THIN" if number == 2 else "SIM_THICK"],
            "pulse_codes": ["SIM_WIRY"], "syndrome_codes": ["SIM_" + syndrome],
            "principle_codes": ["SIM_" + principle], "context_codes": ["SIM_PARTIAL_COMBINATION"],
        },
        "prescription": [{"medicine_code": medicines[name], "dose": None, "unit": "unknown",
                          "basis": "unknown", "formulation": "other", "preparation": "unknown"}
                         for name in selected],
        "outcome_codes": ["SIM_NO_REAL_OUTCOME"],
    }


def build_teaching_bundle(payloads: dict) -> tuple[dict, dict]:
    """Return a simulated bundle and immutable-value evidence sidecar.

    The caller must first use load_reviewed_release to verify the pinned release.
    This function additionally checks aggregate shape, disclosure and selection
    consistency; it does not authenticate a physician or infer a real syndrome.
    An entirely unavailable input returns an empty, non-freezeable scaffold with
    sidecar gate UNAVAILABLE so callers cannot substitute another cohort.
    """
    if not isinstance(payloads, dict) or not set(payloads) <= {"primary", "supplement"}:
        raise AggregateTeachingError("AGGREGATE_SOURCE_MAP_INVALID")
    hashes = {}
    for source, payload in payloads.items():
        try:
            if not isinstance(payload, dict):
                raise ValueError
            validate_payload(payload)
            hashes[source] = payload_hash(payload)
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
            raise AggregateTeachingError("AGGREGATE_PAYLOAD_INVALID") from None
    selected, unavailable = [], []
    for source, group, profile in _TARGETS:
        selection = _select(payloads[source], group) if source in payloads else None
        if selection is None:
            unavailable.append({"source": source, "group": group,
                                "reason": "SOURCE_UNAVAILABLE" if source not in payloads else "NO_DISCLOSED_TRIPLE"})
        else:
            index, row, names = selection
            selected.append((source, group, profile, index, row, names))

    bundle = template_bundle()
    bundle.update(dataset_id="SIMULATED-AGGREGATE-TEACHING", synthetic=True, deidentified=True)
    vocabulary = bundle["vocabulary"]
    vocabulary["conditions"] = [{"code": "SIM_" + code, "label": label} for code, label in _CONDITIONS.items()]
    for category, entries in _VOCABULARY.items():
        vocabulary[category] = [{"code": "SIM_" + code, "label": label} for code, label in entries.items()]
    names = sorted({name for entry in selected for name in entry[-1]})
    medicines = {name: f"SIM_MED_{index:04d}" for index, name in enumerate(names, 1)}
    vocabulary["medicines"] = [{"code": code, "label": name} for name, code in medicines.items()]
    bundle["reviewers"] = [{"reviewer_id": "SIM_AUTHOR", "label": "\u6559\u5b66\u5185\u5bb9\u751f\u6210\u6807\u8bc6\uff08\u975e\u4e34\u5e8a\u5ba1\u9605\uff09"}]
    anchors = []
    for source, group, profile, row_index, row, herbs in selected:
        identity = source.upper() + "_" + profile
        case_id, source_id, physician_id = ("SIM_CASE_" + identity, "SIM_SOURCE_" + identity, "SIM_PHYS_" + identity)
        bundle["sources"].append({"source_id": source_id, "kind": "teaching_note", "sha256": hashes[source],
                                  "review_status": "pending", "reviewer_id": None})
        bundle["physicians"].append({"physician_id": physician_id,
            "label": "\u6559\u5b66\u6a21\u62df\u533b\u5e08 " + identity, "source_ids": [source_id],
            "review_status": "pending", "reviewer_id": None})
        bundle["cases"].append({"case_id": case_id, "subject_id": "SIM_SUBJECT_" + identity,
            "physician_id": physician_id, "source_id": source_id,
            "condition_codes": ["SIM_" + code for code in _PROFILES[profile][0]],
            "visits": [_visit(number, herbs, medicines, profile) for number in (1, 2, 3)]})
        for number in (2, 3):
            bundle["annotations"].append({"annotation_id": f"SIM_NOTE_{identity}_{number}",
                "case_id": case_id, "visit_id": "SIM_VISIT_" + str(number), "author_id": "SIM_AUTHOR",
                "origin": "algorithm", "statement":
                    "\u6559\u5b66\u6a21\u62df\uff1a\u75c7\u72b6\u3001\u8bc1\u578b\u3001\u6cbb\u6cd5\u3001\u65f6\u95f4\u53ca\u52a0\u51cf\u7531\u7a0b\u5e8f\u8bbe\u5b9a\u3002"
                    "\u836f\u540d\u53d6\u81ea\u5df2\u62ab\u9732\u4e09\u836f\u7ec4\u5408\uff0c\u975e\u539f\u60a3\u8005\u5b8c\u6574\u5904\u65b9\uff0c\u4e0d\u636e\u836f\u53cd\u63a8\u771f\u5b9e\u8bc1\u5019\u3002",
                "source_id": source_id, "source_sha256": hashes[source], "status": "draft", "reviewer_id": None})
        anchors.append({"case_id": case_id, "source": source, "group": group,
                        "source_payload_sha256": hashes[source], "table": "combinations",
                        "row_index": row_index, "row": deepcopy(row), "row_sha256": payload_hash(row),
                        "retained_original_fields": "Entire aggregate row and exact medicine labels",
                        "simulated_fields": list(_SIMULATED_FIELDS)})
    validation = validate_bundle(bundle)
    if selected and validation["gate"] == "BLOCK":
        raise AggregateTeachingError("SIMULATED_BUNDLE_INVALID")
    sidecar = {"schema_version": "mingyirx-aggregate-teaching-v1",
               "gate": "PASS_WITH_WARNINGS" if selected else "UNAVAILABLE", "synthetic": True,
               "source_payload_sha256": hashes, "selection": "Disclosed overall triples; descending support count, then exact label",
               "original_statistics_changed": False, "individual_prescriptions_reconstructed": False,
               "clinical_validation": False, "syndromes_inferred_from_prescriptions": False,
               "source_integrity_verification": "Caller must verify the pinned release with load_reviewed_release",
               "case_count": len(selected), "anchors": anchors, "unavailable": unavailable,
               "simulated_fields": list(_SIMULATED_FIELDS),
               "warnings": ["SIMULATED_CASES_NOT_ORIGINAL_PATIENTS", "TRIPLES_NOT_COMPLETE_PRESCRIPTIONS",
                            "ALL_DOSES_UNKNOWN", "SOURCE_AND_PHYSICIAN_ATTRIBUTION_PENDING",
                            "SOURCE_HASHES_DECLARED_ONLY", "NO_CLINICAL_OR_MENTOR_VALIDATION"]}
    return bundle, sidecar
