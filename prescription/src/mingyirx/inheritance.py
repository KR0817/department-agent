"""Constrained local case bundles; review states are declarations, not authentication."""
from __future__ import annotations

import hashlib
import json
import math
import re
import stat
import subprocess
import unicodedata
from pathlib import Path

from . import __version__
from .io import file_sha256


SCHEMA_VERSION = "mingyirx-inheritance-v1"
FREEZE_VERSION = "mingyirx-inheritance-freeze-v1"
MAX_INPUT_BYTES = 4 * 1024 * 1024
CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
VOCABULARIES = ("conditions", "symptoms", "tongues", "pulses", "syndromes",
                "principles", "contexts", "outcomes", "medicines")
ROOT_KEYS = ("schema_version", "dataset_id", "revision", "parent_sha256", "synthetic",
             "local_authorization", "deidentified", "vocabulary", "sources", "reviewers",
             "physicians", "cases", "annotations", "experiences")
PAIR_KEYS = ("case_id", "from_visit_id", "to_visit_id")
ARTIFACTS = ("bundle.json", "validation.json")
_ID = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_PRIVATE_TEXT = re.compile(
    r"[<>]|(?:https?|ftp|file|data|javascript)\s*:|[a-z][a-z0-9+.-]*://|www\.|\w+@\w+\.\w+|"
    r"\b[a-z0-9-]+\.(?:com|org|net|cn|edu|gov|io|test)\b|"
    r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)|"
    r"(?<!\d)\d{17}[\dXx](?!\w)|(?<!\d)\d{15}(?!\d)|"
    r"(?<!\d)(?:19|20)\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?|"
    r"(?<!\d)\d{1,2}[-/.]\d{1,2}[-/.](?:19|20)\d{2}(?!\d)|"
    r"(?<!\d)(?:\+\d[\d ()-]{6,}\d|0\d{2,3}[- ]?\d{7,8})(?!\d)",
    re.IGNORECASE,
)


class InheritanceError(ValueError):
    """A coded failure that never includes submitted values or file paths."""


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def template_bundle() -> dict:
    """Return an empty import scaffold; it cannot be frozen as case evidence."""
    return {"schema_version": SCHEMA_VERSION, "dataset_id": "LOCAL-IMPORT",
            "revision": 1, "parent_sha256": None, "synthetic": False,
            "local_authorization": False, "deidentified": False,
            "vocabulary": {key: [] for key in VOCABULARIES},
            "sources": [], "reviewers": [], "physicians": [], "cases": [],
            "annotations": [], "experiences": []}


def _no_links(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
            raise InheritanceError("PATH_LINK_REJECTED")


def _read_bytes(path: Path) -> bytes:
    try:
        _no_links(path)
        if path.suffix.lower() != ".json" or not stat.S_ISREG(path.stat().st_mode):
            raise InheritanceError("JSON_FILE_REQUIRED")
        with path.open("rb") as handle:
            data = handle.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise InheritanceError("INPUT_SIZE_LIMIT")
        return data
    except OSError:
        raise InheritanceError("INPUT_UNREADABLE") from None


def _object_pairs(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InheritanceError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise InheritanceError("JSON_NONFINITE_NUMBER")


def _decode(data: bytes) -> object:
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=_object_pairs,
                          parse_constant=_nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        if isinstance(error, InheritanceError):
            raise
        raise InheritanceError("JSON_INVALID") from None


def load_bundle(path: Path | str) -> dict:
    """Read one bounded JSON snapshot, rejecting duplicate keys and nonfinite constants."""
    value = _decode(_read_bytes(Path(path)))
    if not isinstance(value, dict):
        raise InheritanceError("ROOT_OBJECT_REQUIRED")
    return value


def _safe_text(value: object, maximum: int) -> bool:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > maximum:
        return False
    text = unicodedata.normalize("NFKC", value)
    long_digits = any(sum(character.isdigit() for character in match.group()) >= 7
                      for match in re.finditer(r"\d[\d ()-]*\d", text))
    return not (_PRIVATE_TEXT.search(text) or long_digits
                or any(unicodedata.category(c).startswith("C") for c in text))


def _positive_finite(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def validate_bundle(payload: object) -> dict:
    """Validate structure, references and review prerequisites without echoing values."""
    errors: list[dict] = []
    warnings: list[dict] = []
    counts: dict[str, int] = {}
    digest = None

    def issue(code: str, path: str) -> None:
        errors.append({"code": code, "path": path})

    def result() -> dict:
        return {"gate": "BLOCK" if errors else ("PASS_WITH_WARNINGS" if warnings else "PASS"),
                "errors": errors, "warnings": warnings, "counts": counts, "content_sha256": digest}

    def shape(value: object, keys: tuple, path: str) -> bool:
        if not isinstance(value, dict):
            issue("OBJECT_REQUIRED", path)
            return False
        if set(value) != set(keys):
            issue("EXACT_KEYS_REQUIRED", path)
            return False
        return True

    def rows(value: object, maximum: int, path: str) -> list:
        if not isinstance(value, list) or len(value) > maximum:
            issue("ARRAY_LIMIT_OR_TYPE", path)
            return []
        return value

    def identifier(value: object, path: str) -> None:
        if not isinstance(value, str) or not _ID.fullmatch(value) or _PRIVATE_TEXT.search(value):
            issue("CODE_INVALID", path)

    def text(value: object, path: str, maximum: int = 80) -> None:
        if not _safe_text(value, maximum):
            issue("TEXT_UNSAFE_OR_INVALID", path)

    def enum(value: object, choices: tuple, path: str) -> None:
        if not isinstance(value, str) or value not in choices:
            issue("ENUM_INVALID", path)

    def integer(value: object, minimum: int, path: str, maximum: int = 1000000) -> None:
        if type(value) is not int or not minimum <= value <= maximum:
            issue("INTEGER_INVALID", path)

    def hash_value(value: object, path: str) -> None:
        if not isinstance(value, str) or not _HASH.fullmatch(value):
            issue("SHA256_INVALID", path)

    def codes(value: object, path: str, maximum: int = 1000) -> None:
        items = rows(value, maximum, path)
        seen = set()
        for index, item in enumerate(items):
            identifier(item, f"{path}[{index}]")
            if isinstance(item, str):
                if item in seen:
                    issue("DUPLICATE_CODE", path)
                seen.add(item)

    def review(row: dict, path: str, annotation: bool = False) -> None:
        field = "status" if annotation else "review_status"
        enum(row[field], ("draft", "approved", "rejected") if annotation else
             ("pending", "confirmed", "rejected"), f"{path}.{field}")
        if row["reviewer_id"] is not None:
            identifier(row["reviewer_id"], f"{path}.reviewer_id")
        if annotation:
            if row[field] == "approved" and row["reviewer_id"] is None:
                issue("REVIEWER_REQUIRED", f"{path}.reviewer_id")
        elif (row[field] == "pending") != (row["reviewer_id"] is None):
            issue("REVIEWER_STATE_MISMATCH", f"{path}.reviewer_id")

    try:
        encoded = _json_bytes(payload)
        digest = _hash(encoded)
        if len(encoded) > MAX_INPUT_BYTES:
            issue("INPUT_SIZE_LIMIT", "$")
            return result()
    except (TypeError, ValueError, RecursionError, UnicodeError):
        issue("JSON_VALUE_INVALID", "$")
        return result()
    if not shape(payload, ROOT_KEYS, "$"):
        return result()
    if payload["schema_version"] != SCHEMA_VERSION:
        issue("SCHEMA_VERSION_INVALID", "$.schema_version")
    identifier(payload["dataset_id"], "$.dataset_id")
    integer(payload["revision"], 1, "$.revision")
    if payload["revision"] == 1:
        if payload["parent_sha256"] is not None:
            issue("PARENT_MUST_BE_NULL", "$.parent_sha256")
    else:
        hash_value(payload["parent_sha256"], "$.parent_sha256")
    for key in ("synthetic", "local_authorization", "deidentified"):
        if type(payload[key]) is not bool:
            issue("BOOLEAN_REQUIRED", "$." + key)
    if payload["synthetic"] is False and not (payload["local_authorization"] is True and payload["deidentified"] is True):
        issue("LOCAL_DECLARATIONS_REQUIRED", "$")
    if shape(payload["vocabulary"], VOCABULARIES, "$.vocabulary"):
        for category in VOCABULARIES:
            for index, row in enumerate(rows(payload["vocabulary"][category], 1000, "$.vocabulary." + category)):
                path = f"$.vocabulary.{category}[{index}]"
                if shape(row, ("code", "label"), path):
                    identifier(row["code"], path + ".code")
                    text(row["label"], path + ".label")
    schemas = {
        "reviewers": (("reviewer_id", "label"), 1000),
        "sources": (("source_id", "kind", "sha256", "review_status", "reviewer_id"), 1000),
        "physicians": (("physician_id", "label", "source_ids", "review_status", "reviewer_id"), 100),
        "cases": (("case_id", "subject_id", "physician_id", "source_id", "condition_codes", "visits"), 100),
        "annotations": (("annotation_id", "case_id", "visit_id", "author_id", "origin", "statement",
                         "source_id", "source_sha256", "status", "reviewer_id"), 4000),
        "experiences": (("experience_id", "title", "condition_codes", "syndrome_codes", "principle_codes",
                         "statement", "scope_note", "exception_note", "supporting_pairs", "exception_pairs",
                         "annotation_ids", "status", "reviewer_id"), 1000),
    }
    for collection, (keys, maximum) in schemas.items():
        for index, row in enumerate(rows(payload[collection], maximum, "$." + collection)):
            path = f"$.{collection}[{index}]"
            if not shape(row, keys, path):
                continue
            for key in keys:
                if key.endswith("_id") and key != "reviewer_id":
                    identifier(row[key], path + "." + key)
            if collection == "reviewers":
                identifier(row["reviewer_id"], path + ".reviewer_id")
            if "label" in row:
                text(row["label"], path + ".label")
            if collection in ("sources", "physicians"):
                review(row, path)
            if collection == "sources":
                enum(row["kind"], ("case_record", "prescription_export", "teaching_note"), path + ".kind")
                hash_value(row["sha256"], path + ".sha256")
            if collection == "physicians":
                codes(row["source_ids"], path + ".source_ids")
                if row["review_status"] == "confirmed" and not row["source_ids"]:
                    issue("CONFIRMED_SOURCE_REQUIRED", path + ".source_ids")
            if collection == "cases":
                codes(row["condition_codes"], path + ".condition_codes")
                visits = rows(row["visits"], 20, path + ".visits")
                if not visits:
                    issue("VISIT_REQUIRED", path + ".visits")
                for number, visit in enumerate(visits):
                    vp = f"{path}.visits[{number}]"
                    if not shape(visit, ("visit_id", "sequence", "offset_days", "order_known", "pre", "prescription", "outcome_codes"), vp):
                        continue
                    identifier(visit["visit_id"], vp + ".visit_id")
                    integer(visit["sequence"], 1, vp + ".sequence")
                    integer(visit["offset_days"], 0, vp + ".offset_days")
                    if type(visit["order_known"]) is not bool:
                        issue("BOOLEAN_REQUIRED", vp + ".order_known")
                    codes(visit["outcome_codes"], vp + ".outcome_codes")
                    pre = visit["pre"]
                    if shape(pre, ("symptoms", "tongue_codes", "pulse_codes", "syndrome_codes", "principle_codes", "context_codes"), vp + ".pre"):
                        for key in ("tongue_codes", "pulse_codes", "syndrome_codes", "principle_codes", "context_codes"):
                            codes(pre[key], vp + ".pre." + key)
                        for sn, symptom in enumerate(rows(pre["symptoms"], 1000, vp + ".pre.symptoms")):
                            sp = f"{vp}.pre.symptoms[{sn}]"
                            if shape(symptom, ("code", "severity"), sp):
                                identifier(symptom["code"], sp + ".code")
                                if symptom["severity"] is not None:
                                    integer(symptom["severity"], 0, sp + ".severity", 3)
                    for dn, drug in enumerate(rows(visit["prescription"], 60, vp + ".prescription")):
                        dp = f"{vp}.prescription[{dn}]"
                        if shape(drug, ("medicine_code", "dose", "unit", "basis", "formulation", "preparation"), dp):
                            identifier(drug["medicine_code"], dp + ".medicine_code")
                            dose = drug["dose"]
                            if dose is not None and not _positive_finite(dose):
                                issue("DOSE_INVALID", dp + ".dose")
                            enum(drug["unit"], ("g", "mg", "ml", "unknown"), dp + ".unit")
                            enum(drug["basis"], ("per_dose", "per_day", "unknown"), dp + ".basis")
                            enum(drug["formulation"], ("decoction", "granule", "other"), dp + ".formulation")
                            text(drug["preparation"], dp + ".preparation")
            if collection in ("annotations", "experiences"):
                review(row, path, annotation=True)
                text(row["statement"], path + ".statement", 2000)
            if collection == "annotations":
                enum(row["origin"], ("contemporaneous", "retrospective", "algorithm"), path + ".origin")
                hash_value(row["source_sha256"], path + ".source_sha256")
            if collection == "experiences":
                for key in ("title", "scope_note", "exception_note"):
                    text(row[key], path + "." + key, 120 if key == "title" else 1000)
                for key in ("condition_codes", "syndrome_codes", "principle_codes", "annotation_ids"):
                    codes(row[key], path + "." + key)
                for key in ("supporting_pairs", "exception_pairs"):
                    for pn, pair in enumerate(rows(row[key], 2000, path + "." + key)):
                        pp = f"{path}.{key}[{pn}]"
                        if shape(pair, PAIR_KEYS, pp):
                            for field in PAIR_KEYS:
                                identifier(pair[field], pp + "." + field)
    if errors:
        return result()

    def registry(items: list, key: str, path: str) -> dict:
        indexed = {}
        for index, row in enumerate(items):
            if row[key] in indexed:
                issue("DUPLICATE_ID", f"{path}[{index}].{key}")
            indexed[row[key]] = row
        return indexed

    vocab = {key: registry(payload["vocabulary"][key], "code", "$.vocabulary." + key) for key in VOCABULARIES}
    reviewers = registry(payload["reviewers"], "reviewer_id", "$.reviewers")
    sources = registry(payload["sources"], "source_id", "$.sources")
    physicians = registry(payload["physicians"], "physician_id", "$.physicians")
    cases = registry(payload["cases"], "case_id", "$.cases")
    annotations = registry(payload["annotations"], "annotation_id", "$.annotations")
    registry(payload["experiences"], "experience_id", "$.experiences")

    def reference(value: str, indexed: dict, path: str) -> None:
        if value not in indexed:
            issue("REFERENCE_UNKNOWN", path)

    def references(values: list, indexed: dict, path: str) -> None:
        for number, value in enumerate(values):
            reference(value, indexed, f"{path}[{number}]")

    def attribution(case: dict) -> bool:
        return (sources.get(case["source_id"], {}).get("review_status") == "confirmed"
                and physicians.get(case["physician_id"], {}).get("review_status") == "confirmed")

    for collection in ("sources", "physicians", "annotations", "experiences"):
        for index, row in enumerate(payload[collection]):
            if row["reviewer_id"] is not None:
                reference(row["reviewer_id"], reviewers, f"$.{collection}[{index}].reviewer_id")
    for index, physician in enumerate(payload["physicians"]):
        path = f"$.physicians[{index}]"
        references(physician["source_ids"], sources, path + ".source_ids")
        if physician["review_status"] == "confirmed" and any(sources.get(code, {}).get("review_status") != "confirmed" for code in physician["source_ids"]):
            issue("CONFIRMED_SOURCE_REQUIRED", path)
    visits_by_case = {}
    pair_status = {}
    for index, case in enumerate(payload["cases"]):
        path = f"$.cases[{index}]"
        reference(case["source_id"], sources, path + ".source_id")
        reference(case["physician_id"], physicians, path + ".physician_id")
        if case["source_id"] not in physicians.get(case["physician_id"], {}).get("source_ids", []):
            issue("CASE_SOURCE_ATTRIBUTION_MISMATCH", path)
        references(case["condition_codes"], vocab["conditions"], path + ".condition_codes")
        visits_by_case[case["case_id"]] = registry(case["visits"], "visit_id", path + ".visits")
        previous = None
        ambiguous = _ambiguous_days(case["visits"])
        for vn, visit in enumerate(case["visits"]):
            vp = f"{path}.visits[{vn}]"
            if previous is not None:
                if visit["sequence"] <= previous["sequence"] or visit["offset_days"] < previous["offset_days"]:
                    issue("VISIT_ORDER_INVALID", vp)
                pair_status[(case["case_id"], previous["visit_id"], visit["visit_id"])] = not (
                    previous["offset_days"] in ambiguous or visit["offset_days"] in ambiguous)
            previous = visit
            references(visit["outcome_codes"], vocab["outcomes"], vp + ".outcome_codes")
            for key, category in (("tongue_codes", "tongues"), ("pulse_codes", "pulses"), ("syndrome_codes", "syndromes"),
                                  ("principle_codes", "principles"), ("context_codes", "contexts")):
                references(visit["pre"][key], vocab[category], vp + ".pre." + key)
            for field, key, category in (("symptoms", "code", "symptoms"), ("prescription", "medicine_code", "medicines")):
                items = visit["pre"][field] if field == "symptoms" else visit[field]
                indexed = registry(items, key, vp + (".pre." if field == "symptoms" else ".") + field)
                references(list(indexed), vocab[category], vp + "." + field)
    for index, row in enumerate(payload["annotations"]):
        path = f"$.annotations[{index}]"
        reference(row["author_id"], reviewers, path + ".author_id")
        reference(row["case_id"], cases, path + ".case_id")
        reference(row["visit_id"], visits_by_case.get(row["case_id"], {}), path + ".visit_id")
        case = cases.get(row["case_id"], {})
        if row["source_id"] != case.get("source_id") or row["source_sha256"] != sources.get(row["source_id"], {}).get("sha256"):
            issue("ANNOTATION_SOURCE_BINDING", path)
        if row["status"] == "approved" and (not case or not attribution(case)):
            issue("APPROVAL_ATTRIBUTION_REQUIRED", path)
    for index, entry in enumerate(payload["experiences"]):
        path = f"$.experiences[{index}]"
        for field, category in (("condition_codes", "conditions"), ("syndrome_codes", "syndromes"), ("principle_codes", "principles")):
            references(entry[field], vocab[category], path + "." + field)
        references(entry["annotation_ids"], annotations, path + ".annotation_ids")
        sets = []
        for field in ("supporting_pairs", "exception_pairs"):
            keys = [tuple(pair[key] for key in PAIR_KEYS) for pair in entry[field]]
            if len(keys) != len(set(keys)):
                issue("DUPLICATE_PAIR_REFERENCE", path + "." + field)
            sets.append(set(keys))
            for pn, key in enumerate(keys):
                if key not in pair_status:
                    issue("ADJACENT_PAIR_REQUIRED", f"{path}.{field}[{pn}]")
                elif not pair_status[key]:
                    issue("PAIR_ORDER_UNRESOLVED", f"{path}.{field}[{pn}]")
        if sets[0] & sets[1]:
            issue("SUPPORT_EXCEPTION_OVERLAP", path)
        if entry["status"] == "approved":
            if not sets[0]:
                issue("APPROVED_SUPPORT_REQUIRED", path)
            if any(key[0] not in cases or not attribution(cases[key[0]]) for key in sets[0] | sets[1]):
                issue("APPROVAL_ATTRIBUTION_REQUIRED", path)
            qualified = [annotations[code] for code in entry["annotation_ids"] if code in annotations
                         and annotations[code]["status"] == "approved" and annotations[code]["origin"] != "algorithm"]
            if not any(a["case_id"] == key[0] and a["visit_id"] in key[1:] for a in qualified for key in sets[0] | sets[1]):
                issue("APPROVED_HUMAN_ANNOTATION_REQUIRED", path)
        if not entry["exception_pairs"]:
            warnings.append({"code": "EXCEPTIONS_NOT_RECORDED", "path": path + ".exception_pairs"})
    counts.update(cases=len(cases), subjects=len({case["subject_id"] for case in payload["cases"]}),
                  visits=sum(len(case["visits"]) for case in payload["cases"]), physicians=len(physicians),
                  sources=len(sources), reviewers=len(reviewers), annotations=len(annotations),
                  experiences=len(payload["experiences"]), pairs=len(pair_status),
                  eligible_pairs=sum(pair_status.values()), unresolved_pairs=sum(not value for value in pair_status.values()))
    if not cases:
        issue("BLANK_BUNDLE", "$.cases")
    warnings.append({"code": "SOURCE_HASHES_DECLARED_ONLY", "path": "$.sources"})
    if payload["synthetic"]:
        warnings.append({"code": "SYNTHETIC_WORKFLOW_ONLY", "path": "$.synthetic"})
    if payload["revision"] > 1:
        warnings.append({"code": "PARENT_CHAIN_NOT_VERIFIED", "path": "$.parent_sha256"})
    if any(row["review_status"] != "confirmed" for row in payload["physicians"] + payload["sources"]):
        warnings.append({"code": "UNCONFIRMED_ATTRIBUTION", "path": "$.physicians"})
    if counts["unresolved_pairs"]:
        warnings.append({"code": "UNRESOLVED_VISIT_ORDER", "path": "$.cases"})
    return result()


def _require_valid(payload: dict) -> dict:
    validation = validate_bundle(payload)
    if validation["gate"] == "BLOCK":
        raise InheritanceError("BUNDLE_VALIDATION_BLOCK")
    return validation


def _ambiguous_days(visits: list[dict]) -> set[int]:
    """Every edge touching an unordered same-day group is unresolved; never bridge it."""
    grouped: dict[int, list] = {}
    for visit in visits:
        grouped.setdefault(visit["offset_days"], []).append(visit)
    return {day for day, group in grouped.items() if len(group) > 1 and any(not visit["order_known"] for visit in group)}


def _dose_change(before: dict, after: dict) -> dict:
    reason = "comparable"
    if before["dose"] is None or after["dose"] is None:
        reason = "missing_dose"
    else:
        for field, unknown in (("unit", "unknown"), ("basis", "unknown"), ("formulation", "other"), ("preparation", "unknown")):
            if before[field] == unknown or after[field] == unknown:
                reason = "unknown_" + field
                break
            if before[field] != after[field]:
                reason = "incompatible_" + field
                break
    delta = after["dose"] - before["dose"] if reason == "comparable" else None
    direction = "unresolved" if delta is None else "increase" if delta > 0 else "decrease" if delta < 0 else "unchanged"
    return {"medicine_code": before["medicine_code"], "before": before["dose"], "after": after["dose"],
            "direction": direction, "delta": delta, "reason": reason}


def _pairs(payload: dict) -> list[dict]:
    pairs = []
    for case in payload["cases"]:
        ambiguous = _ambiguous_days(case["visits"])
        for before, after in zip(case["visits"], case["visits"][1:]):
            unresolved = before["offset_days"] in ambiguous or after["offset_days"] in ambiguous
            row = {key: case[key] for key in ("case_id", "subject_id", "physician_id", "source_id")}
            row.update(from_visit_id=before["visit_id"], to_visit_id=after["visit_id"],
                       interval_days=after["offset_days"] - before["offset_days"],
                       status="unresolved_order" if unresolved else "eligible",
                       added=[], removed=[], retained=[], dose_changes=[], symptom_changes=[])
            if not unresolved:
                old = {drug["medicine_code"]: drug for drug in before["prescription"]}
                new = {drug["medicine_code"]: drug for drug in after["prescription"]}
                row.update(added=sorted(new.keys() - old.keys()), removed=sorted(old.keys() - new.keys()),
                           retained=sorted(old.keys() & new.keys()))
                row["dose_changes"] = [_dose_change(old[code], new[code]) for code in row["retained"]]
                old_s = {symptom["code"]: symptom["severity"] for symptom in before["pre"]["symptoms"]}
                new_s = {symptom["code"]: symptom["severity"] for symptom in after["pre"]["symptoms"]}
                for code in sorted(old_s.keys() | new_s.keys()):
                    first, second = old_s.get(code), new_s.get(code)
                    missing = first is None or second is None
                    direction = "unknown" if missing else "improved" if second < first else "worsened" if second > first else "unchanged"
                    row["symptom_changes"].append({"code": code, "before": first, "after": second,
                                                   "direction": direction, "reason": "missing_severity" if missing else "comparable"})
            pairs.append(row)
    return pairs


def derive_pairs(payload: dict) -> list[dict]:
    _require_valid(payload)
    return _pairs(payload)


def build_view(payload: dict) -> dict:
    validation = _require_valid(payload)
    readiness = {"evidence_state": "SYNTHETIC_WORKFLOW_ONLY" if payload["synthetic"] else "LOCAL_DECLARATIONS_UNVERIFIED",
                 "source_hashes_independently_verified": False, "clinical_effectiveness_verified": False,
                 "parent_chain_verified": False,
                 "confirmed_physicians": sum(row["review_status"] == "confirmed" for row in payload["physicians"]),
                 "confirmed_sources": sum(row["review_status"] == "confirmed" for row in payload["sources"]),
                 "approved_annotations": sum(row["status"] == "approved" for row in payload["annotations"]),
                 "approved_experiences": sum(row["status"] == "approved" for row in payload["experiences"]),
                 "eligible_pairs": validation["counts"]["eligible_pairs"],
                 "unresolved_pairs": validation["counts"]["unresolved_pairs"]}
    return {"validation": validation, "pairs": _pairs(payload), "readiness": readiness}


def _assert_private_location(payload: dict, path: Path) -> None:
    if payload.get("synthetic") is True:
        return
    if not (payload.get("synthetic") is False and payload.get("local_authorization") is True and payload.get("deidentified") is True):
        raise InheritanceError("LOCAL_DECLARATIONS_REQUIRED")
    resolved = path.resolve()
    if not resolved.is_relative_to(CHECKOUT_ROOT / "work") or resolved == CHECKOUT_ROOT / "work":
        raise InheritanceError("RESTRICTED_WORK_PATH_REQUIRED")
    try:
        ignored = subprocess.run(["git", "check-ignore", "--quiet", "--no-index", "--", str(resolved)],
                                 cwd=CHECKOUT_ROOT, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        raise InheritanceError("IGNORED_WORK_PATH_UNVERIFIED") from None
    if ignored.returncode != 0:
        raise InheritanceError("IGNORED_WORK_PATH_UNVERIFIED")


def assert_output_allowed(payload: dict, output_path: Path | str) -> None:
    """Apply the same new-only privacy boundary to frozen packages and local HTML."""
    path = Path(output_path)
    try:
        _no_links(path)
        if path.exists():
            raise InheritanceError("OUTPUT_ALREADY_EXISTS")
        _assert_private_location(payload, path)
    except OSError:
        raise InheritanceError("OUTPUT_PATH_INVALID") from None


def _manifest(payload: dict, validation: dict, artifacts: dict[str, bytes]) -> dict:
    return {"schema_version": FREEZE_VERSION, "bundle_schema_version": SCHEMA_VERSION,
            "software_version": __version__, "validator_sha256": file_sha256(Path(__file__)),
            "synthetic": payload["synthetic"], "content_sha256": validation["content_sha256"],
            "evidence_state": "SYNTHETIC_WORKFLOW_ONLY" if payload["synthetic"] else "LOCAL_DECLARATIONS_UNVERIFIED",
            "parent_chain_verified": False, "source_hashes_independently_verified": False,
            "artifacts": {name: _hash(content) for name, content in artifacts.items()}}


def freeze_bundle(input_path: Path | str, output_dir: Path | str) -> dict:
    """Validate a single input snapshot, then create a new deterministic package."""
    payload = load_bundle(input_path)
    validation = _require_valid(payload)
    output = Path(output_dir)
    assert_output_allowed(payload, output)
    artifacts = {"bundle.json": _json_bytes(payload), "validation.json": _json_bytes(validation)}
    manifest = _manifest(payload, validation, artifacts)
    try:
        output.mkdir(parents=True, exist_ok=False)
        for name, content in {**artifacts, "manifest.json": _json_bytes(manifest)}.items():
            with (output / name).open("xb") as handle:
                handle.write(content)
    except OSError:
        raise InheritanceError("NEW_PACKAGE_WRITE_FAILED") from None
    return manifest


def _verified_snapshot(directory: Path | str) -> tuple[dict, dict]:
    root = Path(directory)
    try:
        _no_links(root)
        paths = list(root.iterdir())
        if {path.name for path in paths} != set(ARTIFACTS) | {"manifest.json"}:
            raise InheritanceError("PACKAGE_MEMBERSHIP_MISMATCH")
        snapshots = {path.name: _read_bytes(path) for path in paths}
        manifest = _decode(snapshots["manifest.json"])
        payload = _decode(snapshots["bundle.json"])
        validation = _require_valid(payload)
        _assert_private_location(payload, root)
        expected_bytes = {"bundle.json": _json_bytes(payload), "validation.json": _json_bytes(validation)}
        if any(snapshots[name] != data for name, data in expected_bytes.items()):
            raise InheritanceError("PACKAGE_ARTIFACT_MISMATCH")
        expected = _manifest(payload, validation, expected_bytes)
        if manifest != expected or snapshots["manifest.json"] != _json_bytes(expected):
            raise InheritanceError("PACKAGE_MANIFEST_MISMATCH")
        summary = dict(validation, artifact_check="PASS", synthetic=payload["synthetic"],
                       evidence_state=expected["evidence_state"], parent_chain_verified=False,
                       source_hashes_independently_verified=False)
        return payload, summary
    except (OSError, TypeError, KeyError, ValueError) as error:
        if isinstance(error, InheritanceError):
            raise
        raise InheritanceError("PACKAGE_VERIFICATION_FAILED") from None


def read_frozen(directory: Path | str) -> dict:
    """Return the bundle from the exact byte snapshot used for verification."""
    return _verified_snapshot(directory)[0]


def verify_frozen(directory: Path | str) -> dict:
    return _verified_snapshot(directory)[1]
