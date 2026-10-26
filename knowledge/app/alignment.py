"""Replay a limited original-punctuation alignment; never call or retrain a model."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from app.benchmark import build_pack, exact_fields, load_fixtures, read_bounded, score, write_json
from app.core import ROOT, parse_json, require_text
from app.verifier import resolve_review

ALLOWED_PUNCTUATION = "\uff0c\u3002\uff1b"
MAX_RESPONSE = 65536


def permitted_gap(text):
    return all(char.isspace() or char in ALLOWED_PUNCTUATION for char in text)


def align_content(content, case):
    """Restore only literal allowed gaps, preserving every model decision and quote."""
    value = parse_json(require_text(content, 32768))
    exact_fields(value, "evidence_status parts")
    parts = value["parts"]
    if not isinstance(parts, list) or not 1 <= len(parts) <= 8:
        raise ValueError("invalid_parts")
    original = require_text(case["claim"], 4000)
    aligned = copy.deepcopy(value)
    cursor, corrections = 0, []
    for index, part in enumerate(parts):
        exact_fields(part, "text verdict quotes")
        text = require_text(part["text"], 4000)
        candidates = []
        start = original.find(text, cursor)
        while start >= 0:
            if not permitted_gap(original[cursor:start]):
                break
            candidates.append(start)
            start = original.find(text, start + 1)
        if len(candidates) != 1:
            raise ValueError("ambiguous_fragment" if candidates else "missing_changed_or_reordered_fragment")
        start = candidates[0]
        gap = original[cursor:start]
        if gap:
            corrections.append({"part_index": index, "start": cursor, "end": start,
                                "text": gap, "placement": "prepend"})
            aligned["parts"][index]["text"] = gap + text
        cursor = start + len(text)
    tail = original[cursor:]
    if not permitted_gap(tail):
        raise ValueError("unsupported_trailing_gap")
    if tail:
        corrections.append({"part_index": len(parts) - 1, "start": cursor, "end": len(original),
                            "text": tail, "placement": "append"})
        aligned["parts"][-1]["text"] += tail
    if "".join(part["text"] for part in aligned["parts"]) != original:
        raise ValueError("incomplete_alignment")
    result = json.dumps(aligned, ensure_ascii=False) if corrections else content
    resolve_review(result, case)
    return result, corrections


def read_bytes(root, name, limit=2 * 1024 * 1024):
    path = root / name
    if path.resolve().parent != root or not path.is_file():
        raise ValueError("artifact_outside_run_or_missing")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("artifact_too_large")
    return raw


def validate_completion(response, model):
    if (not isinstance(response, dict) or response.get("model") != model or
            response.get("done") is not True or response.get("done_reason") != "stop" or
            not isinstance(response.get("message"), dict) or
            response["message"].get("role") != "assistant" or
            response["message"].get("tool_calls") or response.get("error")):
        raise ValueError("invalid_completion")


def replay(run_dir, output_dir):
    """Score a separate derivative while preserving original run bytes and failures."""
    root = Path(run_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("run_directory_required")
    execution_bytes = read_bytes(root, "execution.json")
    execution = parse_json(execution_bytes.decode("utf-8-sig"))
    if (not isinstance(execution, dict) or execution.get("schema") != "local-model-execution-v1" or
            execution.get("clinical_release") is not False or execution.get("strategy") != "itemized" or
            execution.get("suite") not in ("regression", "challenge") or
            not isinstance(execution.get("settings"), dict)):
        raise ValueError("fixed_itemized_execution_required")
    model = require_text(execution.get("model"), 128)
    fixtures = load_fixtures() if execution["suite"] == "regression" else read_bounded(ROOT / "data/semantic_challenges_v06.json")
    pack, _ = build_pack(fixtures)
    case_bytes = read_bytes(root, "cases.json")
    if parse_json(case_bytes.decode("utf-8-sig")) != pack or execution.get("benchmark_sha256") != pack["benchmark_sha256"]:
        raise ValueError("fixed_snapshot_mismatch")
    cases = {case["case_id"]: case for case in pack["cases"]}
    records = execution.get("records")
    if not isinstance(records, list):
        raise ValueError("invalid_execution_records")
    by_id = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid_execution_record")
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or case_id not in cases or case_id in by_id:
            raise ValueError("unknown_or_duplicate_case")
        if record.get("case_sha256") != cases[case_id]["case_sha256"] or type(record.get("http_completed")) is not bool:
            raise ValueError("record_snapshot_mismatch")
        by_id[case_id] = record

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in (("cases.json", case_bytes), ("execution.json", execution_bytes)):
        with (output / name).open("xb") as handle:
            handle.write(raw)
    prediction = {"schema": "semantic-predictions-v1", "benchmark_sha256": pack["benchmark_sha256"],
                  "origin": "unverified_model_output", "predictions": []}
    raw_prediction = {**prediction, "predictions": []}
    summary = {
        "schema": "offline-alignment-replay-v1", "post_observation_replay": True, "model_calls": 0,
        "clinical_release": False, "semantic_atomicity": "not_validated",
        "source_run_directory": str(root), "benchmark_sha256": pack["benchmark_sha256"],
        "source_execution_sha256": hashlib.sha256(execution_bytes).hexdigest(),
        "source_cases_sha256": hashlib.sha256(case_bytes).hexdigest(),
        "execution_copy_meaning": "Original execution bytes; not a new execution of aligned results.",
        "settings": execution["settings"], "suite": execution["suite"], "model": model,
        "alignment_implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "verifier_sha256_used": hashlib.sha256((ROOT / "app/verifier.py").read_bytes()).hexdigest(),
        "allowed_punctuation_codepoints": ["U+FF0C", "U+3002", "U+FF1B"],
        "whitespace_gap_restoration": True, "records": [],
        "limits": ["Post-observation development replay is not an independent model experiment.",
                   "Original response files and original scores remain unchanged.",
                   "Literal alignment does not establish atomicity, semantic support or clinical approval.",
                   "Copied execution counts describe the source run, not aligned predictions."],
    }
    for case in pack["cases"]:
        case_id = case["case_id"]
        record = by_id.get(case_id)
        item = {"case_id": case_id, "case_sha256": case["case_sha256"], "state": "missing",
                "reason": "not_attempted" if record is None else "http_not_completed",
                "source_execution_state": record.get("state") if record else None,
                "source_response_sha256": record.get("response_sha256") if record else None,
                "observed_response_sha256": None, "completion_validated": False,
                "original_strict_status": "not_checked", "format_recovered": False,
                "corrections": [], "raw_state": "missing", "workflow_state": "missing"}
        if record is not None and record["http_completed"]:
            item["reason"] = "response_missing"
            response_name = case_id + ".response.json"
            if (root / response_name).exists():
                item["state"] = "rejected"
                try:
                    if record.get("response_file") != response_name:
                        raise ValueError("response_name_mismatch")
                    response_bytes = read_bytes(root, response_name, MAX_RESPONSE)
                    observed = hashlib.sha256(response_bytes).hexdigest()
                    item["observed_response_sha256"] = observed
                    if observed != record.get("response_sha256"):
                        raise ValueError("response_hash_mismatch")
                    response = parse_json(response_bytes.decode("utf-8"))
                    validate_completion(response, model)
                    item["completion_validated"] = True
                    content = response["message"].get("content")
                    try:
                        _, _, original_trace = resolve_review(content, case)
                        item["original_strict_status"] = original_trace["raw_state"]
                    except (ValueError, TypeError, KeyError, RecursionError):
                        item["original_strict_status"] = "schema_or_coverage_invalid"
                    aligned, corrections = align_content(content, case)
                    raw_result, result, trace = resolve_review(aligned, case)
                    write_json(output / (case_id + ".aligned-content.json"), parse_json(aligned))
                    write_json(output / (case_id + ".review.json"), trace)
                    raw_prediction["predictions"].append(raw_result)
                    prediction["predictions"].append(result)
                    item.update(state="aligned" if corrections else "unchanged", reason=None,
                                corrections=corrections, raw_state=trace["raw_state"],
                                workflow_state=trace["workflow_state"],
                                format_recovered=item["original_strict_status"] == "schema_or_coverage_invalid")
                except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
                    # Only fixed validation codes are retained, never raw model content.
                    reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                    item["reason"] = reason if reason in {
                        "response_name_mismatch", "response_hash_mismatch", "invalid_completion",
                        "artifact_outside_run_or_missing", "artifact_too_large", "invalid_parts",
                        "ambiguous_fragment", "missing_changed_or_reordered_fragment", "unsupported_trailing_gap",
                        "incomplete_alignment", "invalid_fields", "invalid_evidence_status", "invalid_verdict",
                        "invalid_quotes", "invalid_quote", "invalid_text", "incomplete_or_changed_claim",
                        "uncovered_claim_tail"} else "response_or_content_invalid"
        summary["records"].append(item)
        write_json(output / (case_id + ".alignment.json"), item)
    summary["counts"] = {
        "total_cases": len(cases), "source_attempted": len(records),
        "source_http_completed": sum(record["http_completed"] for record in records),
        "completion_validated": sum(item["completion_validated"] for item in summary["records"]),
        "aligned": sum(item["state"] == "aligned" for item in summary["records"]),
        "unchanged": sum(item["state"] == "unchanged" for item in summary["records"]),
        "rejected": sum(item["state"] == "rejected" for item in summary["records"]),
        "missing": sum(item["state"] == "missing" for item in summary["records"]),
        "format_recovered": sum(item["format_recovered"] for item in summary["records"]),
        "raw_invalid": sum(item["raw_state"] == "invalid" for item in summary["records"]),
        "workflow_abstain": sum(item["workflow_state"] == "abstain" for item in summary["records"]),
        "predictions": len(prediction["predictions"]),
    }
    for name, payload in (("predictions.json", prediction), ("aligned-predictions.json", prediction),
                          ("raw-predictions.json", raw_prediction), ("aligned-raw-predictions.json", raw_prediction),
                          ("score.json", score(prediction, fixtures)), ("raw-score.json", score(raw_prediction, fixtures)),
                          ("alignment.json", summary)):
        write_json(output / name, payload)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = replay(args.run_dir, args.output_dir)
    except (ValueError, TypeError, KeyError, OSError, RecursionError):
        parser.exit(2, "Replay not completed. Check fixed snapshots, source artifacts and a new output directory.\n")
    print("Offline replay complete: " + json.dumps(result["counts"], sort_keys=True) + "; model_calls=0.")


if __name__ == "__main__":
    main()
