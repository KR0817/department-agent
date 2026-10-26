"""Run deterministic provenance challenges, not a clinical accuracy benchmark."""

import argparse
import copy
import json
from pathlib import Path

from app.core import ROOT, catalog_hash, check_binding, load_catalog, review_binding_hash
from app.answer_audit import audit_answer


def baseline_request(catalog):
    claim = catalog["claims"][0]
    source = next(s for s in catalog["sources"] if s["id"] == claim["source_id"])
    passage = next(p for p in source["passages"] if p["id"] == claim["passage_id"])
    return {"claim_id": claim["id"], "source_id": source["id"], "passage_id": passage["id"], "claim_text": claim["text"], "quote": passage["text"], "disease": claim["disease"]}


def cases(catalog):
    base = baseline_request(catalog)
    other = catalog["sources"][1]
    yield "original_pending_review", catalog, base, "review_required", {}
    swapped = {**base, "source_id": other["id"], "passage_id": other["passages"][0]["id"], "quote": other["passages"][0]["text"]}
    yield "real_source_and_real_excerpt_wrong_claim", catalog, swapped, "blocked", {"source_identity": "pass", "passage_integrity": "pass", "registered_binding": "fail", "disease_scope": "fail"}
    same_topic = copy.deepcopy(catalog)
    same_topic["sources"][1]["disease"] = base["disease"]
    same_topic["claims"][1]["disease"] = base["disease"]
    yield "simulated_same_disease_wrong_binding", same_topic, swapped, "blocked", {"source_identity": "pass", "passage_integrity": "pass", "disease_scope": "pass", "registered_binding": "fail"}
    multiple = copy.deepcopy(catalog)
    multiple["sources"][0]["passages"].append({"id": "synthetic-other-passage", "text": "Synthetic unrelated method sentence.", "locator": "Synthetic test only"})
    yield "same_source_unrelated_synthetic_passage", multiple, {**base, "passage_id": "synthetic-other-passage", "quote": "Synthetic unrelated method sentence."}, "blocked", {"source_identity": "pass", "passage_integrity": "pass", "disease_scope": "pass", "registered_binding": "fail"}
    yield "unknown_source", catalog, {**base, "source_id": "NOT_A_SOURCE"}, "blocked", {"source_identity": "fail"}
    yield "unknown_passage", catalog, {**base, "passage_id": "NOT_A_PASSAGE"}, "blocked", {"passage_integrity": "fail"}
    yield "invented_quote", catalog, {**base, "quote": "Synthetic fabricated excerpt for testing only."}, "blocked", {"passage_integrity": "fail"}
    yield "rewritten_claim", catalog, {**base, "claim_text": base["claim_text"] + " Universal applicability."}, "review_required", {"registered_binding": "unknown", "clinical_support": "unknown"}
    yield "unknown_claim", catalog, {**base, "claim_id": "NOT_A_CLAIM"}, "blocked", {"registered_binding": "fail"}
    yield "wrong_disease", catalog, {**base, "disease": "gout"}, "blocked", {"disease_scope": "fail"}
    yield "unspecified_disease", catalog, {**base, "disease": "all"}, "review_required", {"disease_scope": "unknown"}
    for source_status in ("retracted", "corrected_unreviewed", "unavailable"):
        changed = copy.deepcopy(catalog)
        changed["sources"][0]["status"] = source_status
        yield source_status, changed, base, "blocked", {"source_usable": "fail"}
    changed = copy.deepcopy(catalog)
    changed["sources"][0]["origin"] = "synthetic"
    yield "synthetic_excluded", changed, base, "blocked", {"provenance": "fail"}
    changed = copy.deepcopy(catalog)
    changed["claims"][0]["review"] = "rejected"
    yield "rejected_claim", changed, base, "blocked", {"review_decision": "fail"}
    changed = copy.deepcopy(catalog)
    changed["sources"][0]["currency"] = "superseded"
    yield "superseded_version", changed, base, "blocked", {"currency": "fail"}
    changed = copy.deepcopy(catalog)
    changed["claims"][0].update(review="approved", reviewer="SYNTHETIC_TEST_REVIEWER", reviewed_at="2026-10-23")
    changed["claims"][0]["reviewed_binding_sha256"] = review_binding_hash(changed["claims"][0], changed["sources"][0])
    yield "review_alone_not_current", changed, base, "review_required", {"clinical_support": "pass", "currency": "unknown"}
    changed["sources"][0]["currency"] = "current"
    yield "simulated_review_and_current_reference", changed, base, "eligible", {"clinical_support": "pass", "currency": "pass"}
    yield "edited_after_simulated_review", changed, {**base, "claim_text": "Synthetic changed assertion."}, "review_required", {"clinical_support": "unknown"}
    mutated = copy.deepcopy(changed)
    mutated["sources"][0]["passages"][0]["text"] = "Synthetic changed source content."
    yield "source_changed_after_review", mutated, {**base, "quote": "Synthetic changed source content."}, "review_required", {"passage_integrity": "pass", "clinical_support": "unknown"}


def evaluate(catalog=None):
    catalog = catalog or load_catalog()
    results = []
    for name, fixture, request, expected, check_expectations in cases(catalog):
        actual = check_binding(fixture, request)
        states = {c["name"]: c["state"] for c in actual["checks"]}
        passed = actual["status"] == expected and all(states.get(k) == v for k, v in check_expectations.items()) and actual["clinical_release"] is False
        results.append({"case": name, "expected": expected, "actual": actual["status"], "passed": passed, "check_expectations": check_expectations})
    for name, request, expected, expected_counts in answer_cases(catalog):
        actual = audit_answer(catalog, request)
        passed = actual["status"] == expected and all(actual["coverage"][k] == v for k, v in expected_counts.items()) and not actual["clinical_release"]
        results.append({"case": name, "operation": "audit-answer", "expected": expected, "actual": actual["status"], "passed": passed, "coverage_expectations": expected_counts})
    return {"suite": "deterministic_binding_and_coverage_challenges", "fixture_origin": "mixed_public_excerpts_and_simulated_mutations", "corpus_sha256": catalog_hash(catalog), "semantic_accuracy": None, "clinical_validation": "NOT_RUN", "limit": "These cases assess software behavior, not medical entailment, atomic claim extraction or patient safety.", "total": len(results), "passed": sum(r["passed"] for r in results), "results": results}


def answer_cases(catalog):
    claim = catalog["claims"][0]
    link = {"claim_id": claim["id"], "source_id": claim["source_id"], "passage_id": claim["passage_id"]}
    base = {"answer": claim["text"], "disease": claim["disease"], "corpus_sha256": catalog_hash(catalog), "bindings": [{"unit_id": "u1", "citations": [link]}]}
    yield "answer_pending_canonical", base, "review_required", {"cited_units": 1}
    yield "answer_uncited_all", {**base, "bindings": []}, "blocked", {"uncited_units": 1}
    yield "answer_uncited_tail", {**base, "answer": base["answer"] + " Synthetic unchecked claim."}, "blocked", {"total_units": 2, "uncited_units": 1}
    yield "answer_repeated_citation_padding", {**base, "answer": base["answer"] + " Synthetic unchecked claim.", "bindings": [{"unit_id": "u1", "citations": [link] * 8}]}, "blocked", {"duplicate_citations": 7, "cited_units": 1, "uncited_units": 1}
    other = catalog["claims"][1]
    wrong = {**link, "source_id": other["source_id"], "passage_id": other["passage_id"]}
    yield "answer_valid_plus_wrong_reference", {**base, "bindings": [{"unit_id": "u1", "citations": [link, wrong]}]}, "blocked", {"blocked_units": 1}
    yield "answer_compound_assertion", {**base, "answer": claim["text"][:-1] + ", with universal applicability."}, "review_required", {"total_units": 1, "review_required_units": 1}
    yield "answer_unseen_claim_with_known_binding", {**base, "answer": "Synthetic unregistered assertion."}, "review_required", {"cited_units": 1, "review_required_units": 1}
    yield "answer_unknown_source", {**base, "bindings": [{"unit_id": "u1", "citations": [{**link, "source_id": "UNKNOWN_SYNTHETIC_SOURCE"}]}]}, "blocked", {"blocked_units": 1}


def main():
    parser = argparse.ArgumentParser(description="Evaluate deterministic evidence bindings")
    parser.add_argument("--output", type=Path, default=ROOT / "work" / "evaluation.json")
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Engineering cases: {report['passed']}/{report['total']}; semantic and clinical validation NOT RUN")
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
