"""Explicit-rule intake candidates; no model, identity matching or clinical inference.

Source references bind the sorted unique uploaded-file hashes for each exact
subject/episode/physician group. The server retains original per-file hashes and
field evidence in its private intake records. Importer annotations remain draft
algorithm records; an operator review marker is not physician authentication.
Missing dates with a complete explicit sequence use zero relative offsets and
unknown order, so no interval or transition is interpreted. The nonsynthetic
bundle's declaration flags are usable only after the server's explicit commit
confirmation/deidentification gate; preview must not expose that bundle.
"""
from __future__ import annotations

import csv
from datetime import date
import hashlib
import io
import json
import math
import re
import unicodedata

from .inheritance import InheritanceError, derive_pairs, validate_bundle


SCHEMA_VERSION = "mingyirx-case-import-v1"
MAX_TEXT_BYTES = 1024 * 1024
MAX_RECORDS = 1000
MAX_FIELD_CHARS = 2000
ID_FIELDS = ("subject_code", "episode_code", "physician_code", "visit_code")
TEXT_FIELDS = ("condition", "symptoms", "tongue", "pulse", "syndrome", "principle", "prescription")
EDITABLE_FIELDS = (*ID_FIELDS, "date", "sequence", *TEXT_FIELDS)
RECORD_FIELDS = ("record_id", *EDITABLE_FIELDS, "source_sha256", "evidence")
FORMATS = ("txt", "text", "csv", "json", "docx", "pdf", "png", "jpg", "jpeg", "bmp", "ocr")
_CODE = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_ALIASES = {
    "subject_code": ("subject", "subject code", "subject_id", "patient code", "patient_code", "\u53d7\u8bd5\u8005\u7f16\u7801", "\u60a3\u8005\u7f16\u7801", "\u60a3\u8005\u7f16\u53f7"),
    "episode_code": ("episode", "episode code", "episode_id", "case code", "case_code", "\u533b\u6848\u7f16\u7801", "\u75c5\u4f8b\u7f16\u7801", "\u7597\u7a0b\u7f16\u7801"),
    "physician_code": ("physician", "physician code", "physician_id", "doctor_code", "\u533b\u5e08\u7f16\u7801", "\u533b\u751f\u7f16\u7801"),
    "visit_code": ("visit", "visit code", "visit_id", "\u8bbf\u6b21\u7f16\u7801", "\u5c31\u8bca\u7f16\u7801", "\u8bbf\u6b21\u7f16\u53f7"),
    "date": ("visit_date", "visit date", "\u65e5\u671f", "\u5c31\u8bca\u65e5\u671f"),
    "sequence": ("visit_sequence", "\u5e8f\u53f7", "\u8bbf\u6b21\u5e8f\u53f7", "\u6b21\u5e8f"),
    "condition": ("diagnosis", "\u75c5\u79cd", "\u8bca\u65ad"),
    "symptoms": ("symptom", "\u75c7\u72b6", "\u4e3b\u8bc9"),
    "tongue": ("\u820c\u8c61", "\u820c\u8bca"),
    "pulse": ("\u8109\u8c61", "\u8109\u8bca"),
    "syndrome": ("\u8bc1\u5019", "\u8bc1\u578b", "\u8fa8\u8bc1"),
    "principle": ("treatment principle", "\u6cbb\u6cd5", "\u6cbb\u5219"),
    "prescription": ("medicines", "\u5904\u65b9", "\u4e2d\u836f\u5904\u65b9", "\u7528\u836f"),
}
_HEADERS = {alias.casefold(): field for field, aliases in _ALIASES.items() for alias in (field, *aliases)}
_LABEL_WITHOUT_COLON = re.compile(r"^(" + "|".join(re.escape(key) for key in sorted(_HEADERS, key=len, reverse=True)) + r")[ \t]+(.+)$", re.I)
_UNKNOWN = {"unknown", "not recorded", "n/a", "na", "null", "\u672a\u77e5", "\u672a\u8bb0\u5f55", "\u4e0d\u8be6"}
_RX_SEPARATOR = re.compile(r"[;,\uff1b\uff0c\u3001\n]+")
_RX_NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
_RX_SOURCE_UNIT = r"g|mg|ml|\u6beb\u514b|\u514b|\u6beb\u5347|\u5305"
_RX_TAIL = re.compile(rf"(?P<first>{_RX_SOURCE_UNIT})?(?:\s*[-~\u2013\u81f3]\s*(?P<range>{_RX_NUMBER})\s*(?P<second>{_RX_SOURCE_UNIT})?)?", re.I)
_RX_CONTINUATION = re.compile(rf"[A-Za-z\u3400-\u9fff][A-Za-z\u3400-\u9fff_-]*\s*{_RX_NUMBER}\s*(?:g|mg|ml|\u6beb\u514b|\u514b|\u6beb\u5347)", re.I)


class CaseImportError(InheritanceError):
    """Coded intake failure; submitted text and paths are never echoed."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _strict_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CaseImportError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise CaseImportError("JSON_NONFINITE_NUMBER")


def _field(header: str) -> str | None:
    return _HEADERS.get(unicodedata.normalize("NFKC", header).strip().casefold())


def _iso_date(value: str) -> str:
    candidate = re.sub(r"[/.\u5e74\u6708]", "-", value.strip()).removesuffix("\u65e5")
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", candidate)
    if not match:
        raise ValueError("DATE_INVALID")
    return date(*(int(part) for part in match.groups())).isoformat()


def _prescription_line(value: str) -> bool:
    """Only complete drug/number/unit syntax may extend an unlabeled line."""
    tokens = [token.strip() for token in _RX_SEPARATOR.split(value) if token.strip()]
    return bool(tokens) and all(_RX_CONTINUATION.fullmatch(token) for token in tokens)


def _candidate(values: dict, evidence: dict, source_sha256: str, index: int, warnings: list) -> dict:
    row = {key: None if key == "sequence" else "" for key in EDITABLE_FIELDS}
    for key in EDITABLE_FIELDS:
        value = values.get(key, row[key])
        if key == "sequence":
            if value in (None, ""):
                continue
            if (type(value) is int and value > 0) or (isinstance(value, str) and re.fullmatch(r"[1-9]\d{0,5}", value.strip())):
                row[key] = int(value)
            else:
                warnings.append({"code": "SEQUENCE_UNRESOLVED", "record": index, "field": key})
        elif isinstance(value, str):
            row[key] = value.strip()
            try:
                row[key].encode("utf-8")
            except UnicodeError:
                raise CaseImportError("FIELD_ENCODING_INVALID") from None
            if len(row[key]) > MAX_FIELD_CHARS:
                raise CaseImportError("FIELD_SIZE_LIMIT")
            if key == "date" and row[key]:
                try:
                    row[key] = _iso_date(row[key])
                except ValueError:
                    row[key] = ""
                    warnings.append({"code": "DATE_UNRESOLVED", "record": index, "field": key})
        elif value is not None:
            warnings.append({"code": "FIELD_TYPE_UNRESOLVED", "record": index, "field": key})
    return {"record_id": "REC-" + _digest([source_sha256, row, evidence])[:24], **row,
            "source_sha256": source_sha256, "evidence": evidence}


def _json_records(text: str) -> list[tuple[dict, dict]]:
    """Locate actual JSON key lines without searching strings inside quoted values."""
    decoder = json.JSONDecoder(object_pairs_hook=_strict_object, parse_constant=_nonfinite)
    try:
        root = decoder.decode(text)
        if not isinstance(root, list) or len(root) > MAX_RECORDS:
            raise CaseImportError("JSON_RECORD_ARRAY_REQUIRED")
        position = text.index("[") + 1
        result = []
        for row in root:
            while position < len(text) and (text[position].isspace() or text[position] == ","):
                position += 1
            if not isinstance(row, dict):
                raise CaseImportError("JSON_RECORD_OBJECT_REQUIRED")
            start = position
            _, position = decoder.raw_decode(text, position)
            cursor, locations = start + 1, {}
            while cursor < position - 1:
                while cursor < position - 1 and (text[cursor].isspace() or text[cursor] == ","):
                    cursor += 1
                if cursor >= position - 1:
                    break
                line = text.count("\n", 0, cursor) + 1
                key, cursor = decoder.raw_decode(text, cursor)
                while text[cursor].isspace():
                    cursor += 1
                cursor += 1
                while text[cursor].isspace():
                    cursor += 1
                _, cursor = decoder.raw_decode(text, cursor)
                locations[key] = [line]
            result.append((row, locations))
        return result
    except (ValueError, UnicodeError, RecursionError, IndexError) as error:
        if isinstance(error, CaseImportError):
            raise
        raise CaseImportError("JSON_INVALID") from None


def recognize_text(text: str, source_sha256: str, format_name: str) -> dict:
    """Recognize explicit labels; all results remain editable unapproved candidates."""
    if not isinstance(text, str) or not isinstance(source_sha256, str) or not _HASH.fullmatch(source_sha256):
        raise CaseImportError("TEXT_OR_SOURCE_HASH_INVALID")
    try:
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise CaseImportError("TEXT_SIZE_LIMIT")
    except UnicodeError:
        raise CaseImportError("TEXT_ENCODING_INVALID") from None
    if format_name not in FORMATS:
        raise CaseImportError("FORMAT_UNSUPPORTED")
    if "\x00" in text:
        raise CaseImportError("TEXT_CONTROL_CHARACTER")
    text = text.lstrip("\ufeff")
    warnings: list[dict] = []
    raw: list[tuple[dict, dict]] = []
    if format_name == "json":
        raw = _json_records(text)
    elif format_name == "csv":
        try:
            reader = csv.reader(io.StringIO(text, newline=""), strict=True)
            headers = next(reader, None)
            if not headers:
                raise CaseImportError("CSV_HEADER_REQUIRED")
            recognized = [_field(header) for header in headers]
            named = [key for key in recognized if key]
            if len(named) != len(set(named)):
                raise CaseImportError("DUPLICATE_FIELD_HEADER")
            previous_line = reader.line_num
            for values in reader:
                lines = list(range(previous_line + 1, reader.line_num + 1))
                previous_line = reader.line_num
                if not any(value.strip() for value in values):
                    continue
                if len(values) != len(headers):
                    raise CaseImportError("CSV_COLUMN_COUNT")
                raw.append((dict(zip(headers, values)), {header: lines for header in headers}))
                if len(raw) > MAX_RECORDS:
                    raise CaseImportError("RECORD_LIMIT")
        except csv.Error:
            raise CaseImportError("CSV_INVALID") from None
    else:
        values, locations, context, context_locations = {}, {}, {}, {}
        last_field = None

        def flush() -> None:
            nonlocal values, locations, last_field
            if values and any(key not in ID_FIELDS[:3] for key in values):
                raw.append(({**context, **values}, {**context_locations, **locations}))
            values, locations, last_field = {}, {}, None

        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or re.fullmatch(r"[-=]{3,}", stripped):
                if "visit_code" in values and any(key in values for key in TEXT_FIELDS):
                    flush()
                continue
            match = re.match(r"^([^:\uff1a]{1,80})[:\uff1a]\s*(.*)$", stripped)
            if not match:
                match = _LABEL_WITHOUT_COLON.match(stripped)
            if not match and _field(stripped):
                match = (stripped, stripped, "")
            key = _field(match[1]) if match else None
            if key:
                if key in ID_FIELDS[:3] and "visit_code" in values:
                    flush()
                if key == "subject_code":
                    context, context_locations = {}, {}
                    for contextual in ID_FIELDS[1:3]:
                        if contextual in values:
                            context[contextual] = values[contextual]
                            context_locations[contextual] = locations[contextual][:]
                elif key == "visit_code" and "visit_code" in values:
                    flush()
                if key in values:
                    warnings.append({"code": "REPEATED_FIELD_REQUIRES_REVIEW", "line": number, "record": len(raw) + 1})
                    values[key] += "\n" + match[2]
                    locations[key].append(number)
                else:
                    values[key], locations[key] = match[2], [number]
                if key in ID_FIELDS[:3]:
                    context[key], context_locations[key] = values[key], locations[key][:]
                last_field = key
            elif (not match and last_field and values[last_field] == "" and locations[last_field][-1] == number - 1
                  and (last_field != "prescription" or _prescription_line(stripped))):
                values[last_field] = stripped
                locations[last_field].append(number)
                if last_field in ID_FIELDS[:3]:
                    context[last_field], context_locations[last_field] = stripped, locations[last_field][:]
            elif (not match and last_field == "prescription" and locations[last_field][-1] == number - 1
                  and _prescription_line(stripped)):
                values[last_field] += "\n" + stripped
                locations[last_field].append(number)
            else:
                warnings.append({"code": "UNRECOGNIZED_LINE", "line": number, "record": len(raw) + 1})
        flush()
    if len(raw) > MAX_RECORDS:
        raise CaseImportError("RECORD_LIMIT")
    records = []
    for index, (source, locations) in enumerate(raw, 1):
        values, evidence = {}, {}
        for header, value in source.items():
            key = _field(header)
            if key:
                if key in values:
                    raise CaseImportError("DUPLICATE_FIELD_HEADER")
                values[key], evidence[key] = value, locations[header]
            elif header not in ("record_id", "source_sha256", "evidence"):
                warnings.append({"code": "UNRECOGNIZED_FIELD", "line": locations[header][0], "record": index})
        if values:
            records.append(_candidate(values, evidence, source_sha256, index, warnings))
    if not records:
        warnings.append({"code": "NO_RECOGNIZED_RECORDS", "line": 0, "record": 0})
    return {"schema_version": SCHEMA_VERSION, "records": records, "warnings": warnings}


def _split_labels(value: str) -> list[str]:
    # Commas and enumeration punctuation may remain inside a negated phrase.
    labels = [item.strip() for item in re.split(r"[;\n\uff1b]+", value) if item.strip()]
    return list(dict.fromkeys(label for label in labels if label.casefold() not in _UNKNOWN))


def _prescription(value: str, position: int, warnings: list, errors: list) -> list[dict]:
    drugs, seen = [], set()
    for token in _RX_SEPARATOR.split(value):
        token = token.strip()
        if not token or token.casefold() in _UNKNOWN:
            continue
        match = re.match(r"^(?P<name>[^\d?+<>=\-~\u2264\u2265]+?)\s*(?P<qual>[<>~\u2264\u2265]?)\s*(?P<dose>[+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(?P<tail>.*)$", token)
        dose, unit = None, "unknown"
        if match:
            name, tail = match["name"].strip(), match["tail"].strip()
            # Unknown prose may be another drug or a negation; never discard it.
            tail_match = _RX_TAIL.fullmatch(tail)
            if not tail_match:
                errors.append({"code": "PRESCRIPTION_TOKEN_AMBIGUOUS", "record": position, "field": "prescription"})
                continue
            try:
                number = float(match["dose"])
                if not match["qual"] and not tail_match["range"] and math.isfinite(number) and number > 0:
                    dose = number
            except (ValueError, OverflowError):
                pass
            units = {item.lower() for item in (tail_match["first"], tail_match["second"]) if item}
            if len(units) == 1 and next(iter(units)) in ("g", "mg", "ml"):
                unit = next(iter(units))
        else:
            name = re.sub(r"\s*(?:\u9002\u91cf|\u5242\u91cf\u4e0d\u8be6|\u672a\u8bb0\u5f55|unknown|\?+)\s*$", "", token, flags=re.I).strip()
        if not name or re.search(r"[\d<>?=]", name):
            errors.append({"code": "PRESCRIPTION_TOKEN_INVALID", "record": position, "field": "prescription"})
            continue
        if name in seen:
            errors.append({"code": "DUPLICATE_MEDICINE", "record": position, "field": "prescription"})
            continue
        seen.add(name)
        if dose is None:
            warnings.append({"code": "DOSE_UNRESOLVED", "record": position, "field": "prescription"})
        if unit == "unknown":
            warnings.append({"code": "UNIT_UNRESOLVED", "record": position, "field": "prescription"})
        drugs.append({"label": name, "dose": dose, "unit": unit, "basis": "unknown",
                      "formulation": "other", "preparation": "unknown"})
    return drugs


def prepare_import(records: object, *, synthetic: bool = False) -> dict:
    """Convert reviewed explicit records; the caller owns the real-data commit gate."""
    errors: list[dict] = []
    warnings: list[dict] = []
    counts = {"input_records": len(records) if isinstance(records, list) else 0,
              "records": 0, "duplicates": 0, "cases": 0, "subjects": 0, "visits": 0, "pairs": 0}

    def issue(code: str, record: int = 0, field: str = "records") -> None:
        errors.append({"code": code, "record": record, "field": field})

    def blocked() -> dict:
        return {"gate": "BLOCK", "errors": errors, "warnings": warnings, "bundle": None, "pairs": [], "counts": counts}

    if type(synthetic) is not bool:
        issue("SYNTHETIC_FLAG_INVALID")
    if not isinstance(records, list) or not records or len(records) > MAX_RECORDS:
        issue("RECORD_ARRAY_REQUIRED")
        return blocked()
    for index, row in enumerate(records, 1):
        if not isinstance(row, dict) or set(row) != set(RECORD_FIELDS):
            issue("EXACT_RECORD_KEYS_REQUIRED", index)
            continue
        for key in ("record_id", *ID_FIELDS):
            if not isinstance(row[key], str) or not _CODE.fullmatch(row[key]):
                issue("CODE_REQUIRED", index, key)
        for key in TEXT_FIELDS:
            if not isinstance(row[key], str) or len(row[key]) > MAX_FIELD_CHARS:
                issue("TEXT_FIELD_INVALID", index, key)
            else:
                try:
                    row[key].encode("utf-8")
                except UnicodeError:
                    issue("TEXT_FIELD_INVALID", index, key)
        if not isinstance(row["source_sha256"], str) or not _HASH.fullmatch(row["source_sha256"]):
            issue("SOURCE_SHA256_INVALID", index, "source_sha256")
        if row["sequence"] is not None and (type(row["sequence"]) is not int or not 1 <= row["sequence"] <= 1000000):
            issue("SEQUENCE_INVALID", index, "sequence")
        try:
            if not isinstance(row["date"], str) or (row["date"] and (date.fromisoformat(row["date"]).isoformat() != row["date"])):
                issue("DATE_INVALID", index, "date")
        except ValueError:
            issue("DATE_INVALID", index, "date")
        evidence = row["evidence"]
        if not isinstance(evidence, dict) or any(key not in EDITABLE_FIELDS for key in evidence):
            issue("EVIDENCE_INVALID", index, "evidence")
        elif any(value != "user-reviewed" and (not isinstance(value, list) or len(value) > 10000
                 or any(type(line) is not int or not 1 <= line <= 1000000 for line in value)
                 or len(value) != len(set(value))) for value in evidence.values()):
            issue("EVIDENCE_INVALID", index, "evidence")
    if errors:
        return blocked()
    groups, duplicates, signatures = {}, {}, {}
    for index, row in enumerate(records, 1):
        group_key = tuple(row[key] for key in ID_FIELDS[:3])
        visit_key = (*group_key, row["visit_code"])
        signature = _canonical({key: row[key] for key in EDITABLE_FIELDS})
        duplicates.setdefault(group_key, set()).add(row["source_sha256"])
        if visit_key in signatures:
            if signatures[visit_key] != signature:
                issue("CONFLICTING_VISIT", index, "visit_code")
            else:
                counts["duplicates"] += 1
                warnings.append({"code": "DUPLICATE_VISIT_IGNORED", "record": index, "field": "visit_code"})
            continue
        signatures[visit_key] = signature
        groups.setdefault(group_key, []).append((index, row))
    counts["records"] = len(signatures)
    if errors:
        return blocked()
    if len(groups) > 100:
        issue("CASE_LIMIT")
        return blocked()
    bundle = {"schema_version": "mingyirx-inheritance-v1", "dataset_id": "SYNTHETIC-CASE-IMPORT" if synthetic else "LOCAL-CASE-IMPORT",
              "revision": 1, "parent_sha256": None, "synthetic": synthetic, "local_authorization": True,
              "deidentified": True, "vocabulary": {key: [] for key in ("conditions", "symptoms", "tongues", "pulses", "syndromes", "principles", "contexts", "outcomes", "medicines")},
              "sources": [], "reviewers": [{"reviewer_id": "IMPORT-OPERATOR", "label": "Synthetic import operator" if synthetic else "Local import operator declaration"}],
              "physicians": [], "cases": [], "annotations": [], "experiences": []}
    vocab, physicians = {}, {}

    def vocabulary(category: str, label: str) -> str:
        code = category[:3].upper() + "-" + _digest(label)[:20]
        if (category, code) not in vocab:
            bundle["vocabulary"][category].append({"code": code, "label": label})
            vocab[category, code] = label
        elif vocab[category, code] != label:
            issue("VOCABULARY_COLLISION")
        return code

    for group_key in sorted(groups):
        members = groups[group_key]
        first_position = members[0][0]
        if len(members) > 20:
            issue("VISIT_LIMIT", first_position, "visit_code")
            continue
        # Case-level condition unions would reveal later-visit information.
        condition_sets = {frozenset(_split_labels(row["condition"])) for _, row in members}
        if len(condition_sets) != 1:
            issue("CONDITION_VARIATION_REQUIRES_REVIEW", first_position, "condition")
            continue
        dated = all(row["date"] for _, row in members)
        sequenced = all(row["sequence"] is not None for _, row in members)
        explicit_sequences = [row["sequence"] for _, row in members if row["sequence"] is not None]
        if len(explicit_sequences) != len(set(explicit_sequences)):
            issue("DUPLICATE_SEQUENCE", first_position, "sequence")
            continue
        if not dated and len(members) > 1 and not sequenced:
            issue("ORDER_INPUT_REQUIRED", first_position, "date")
            continue
        if dated:
            members = sorted(members, key=lambda item: (item[1]["date"], item[1]["sequence"] if item[1]["sequence"] is not None else 1000001, item[1]["visit_code"]))
            dated_sequences = [row["sequence"] for _, row in members if row["sequence"] is not None]
            if any(left >= right for left, right in zip(dated_sequences, dated_sequences[1:])):
                issue("DATE_SEQUENCE_CONFLICT", first_position, "sequence")
                continue
            origin = date.fromisoformat(members[0][1]["date"])
        else:
            members = sorted(members, key=lambda item: item[1]["sequence"] or 0)
            origin = None
            warnings.append({"code": "DATE_MISSING_INTERVAL_UNKNOWN", "record": first_position, "field": "date"})
        group_id = _digest(group_key)[:24]
        case_id, source_id = "CASE-" + group_id, "SRC-" + group_id
        source_hash = _digest(sorted(duplicates[group_key]))
        bundle["sources"].append({"source_id": source_id, "kind": "case_record", "sha256": source_hash, "review_status": "pending", "reviewer_id": None})
        physician_id = group_key[2]
        physicians.setdefault(physician_id, {"physician_id": physician_id, "label": physician_id,
                                           "source_ids": [], "review_status": "pending", "reviewer_id": None})["source_ids"].append(source_id)
        case = {"case_id": case_id, "subject_id": group_key[0], "physician_id": physician_id,
                "source_id": source_id, "condition_codes": [], "visits": []}
        day_sequences: dict[str, bool] = {}
        for _, row in members:
            day_sequences[row["date"]] = day_sequences.get(row["date"], True) and row["sequence"] is not None
        for stored_sequence, (position, row) in enumerate(members, 1):
            for label in _split_labels(row["condition"]):
                code = vocabulary("conditions", label)
                if code not in case["condition_codes"]:
                    case["condition_codes"].append(code)
            pre = {"symptoms": [{"code": vocabulary("symptoms", label), "severity": None} for label in _split_labels(row["symptoms"])],
                   "tongue_codes": [vocabulary("tongues", label) for label in _split_labels(row["tongue"])],
                   "pulse_codes": [vocabulary("pulses", label) for label in _split_labels(row["pulse"])],
                   "syndrome_codes": [vocabulary("syndromes", label) for label in _split_labels(row["syndrome"])],
                   "principle_codes": [vocabulary("principles", label) for label in _split_labels(row["principle"])], "context_codes": []}
            drugs = _prescription(row["prescription"], position, warnings, errors)
            prescription = [{"medicine_code": vocabulary("medicines", drug["label"]), **{key: value for key, value in drug.items() if key != "label"}} for drug in drugs]
            if prescription:
                warnings.append({"code": "DOSE_BASIS_AND_PREPARATION_UNKNOWN", "record": position, "field": "prescription"})
            offset = (date.fromisoformat(row["date"]) - origin).days if origin else 0
            case["visits"].append({"visit_id": row["visit_code"], "sequence": stored_sequence,
                                   "offset_days": offset, "order_known": bool(dated and day_sequences[row["date"]]),
                                   "pre": pre, "prescription": prescription, "outcome_codes": []})
            reviewed = any(value == "user-reviewed" for value in row["evidence"].values())
            statement = "Rule-extracted intake candidate; original field evidence remains in the private intake record."
            if reviewed:
                statement += " An operator marked edited fields reviewed; this is not physician attribution."
            bundle["annotations"].append({"annotation_id": "ANN-" + _digest([group_key, row["visit_code"]])[:24],
                "case_id": case_id, "visit_id": row["visit_code"], "author_id": "IMPORT-OPERATOR", "origin": "algorithm",
                "statement": statement, "source_id": source_id, "source_sha256": source_hash, "status": "draft", "reviewer_id": None})
        bundle["cases"].append(case)
    bundle["physicians"] = [physicians[key] for key in sorted(physicians)]
    if errors:
        return blocked()
    validation = validate_bundle(bundle)
    if validation["gate"] == "BLOCK":
        for error in validation["errors"]:
            issue("BUNDLE_" + error["code"], 0, "bundle")
        return blocked()
    pairs = derive_pairs(bundle)
    counts.update({key: validation["counts"][key] for key in ("cases", "subjects", "visits", "pairs")})
    counts.update(eligible_pairs=validation["counts"]["eligible_pairs"], unresolved_pairs=validation["counts"]["unresolved_pairs"])
    warnings.extend({"code": warning["code"], "record": 0, "field": "bundle"} for warning in validation["warnings"])
    return {"gate": "PASS_WITH_WARNINGS" if warnings else "PASS", "errors": [], "warnings": warnings,
            "bundle": bundle, "pairs": pairs, "counts": counts}
