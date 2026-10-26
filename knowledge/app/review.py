"""Prepare evidence for human assessment; never create a review decision."""

import copy

from app.core import catalog_hash, check_binding, public_catalog, review_binding_hash

DIMENSIONS = (
    "population", "intervention_formulation", "comparator", "outcome_time",
    "direction_magnitude", "study_design", "recommendation_strength",
    "evidence_certainty", "consensus", "causal_strength",
)
DIMENSION_GUIDANCE = {
    "population": "Match species, diagnosis, disease activity and TCM syndrome criteria; identify exclusions and special populations.",
    "intervention_formulation": "Match exact formula ingredients, preparation, dose, duration and co-interventions; a formula name alone is insufficient.",
    "comparator": "Match placebo, usual care or active comparator, including background treatment.",
    "outcome_time": "Match outcome definition and follow-up; distinguish surrogate or animal endpoints from patient clinical outcomes.",
    "direction_magnitude": "Preserve effect direction, absolute/relative scale, uncertainty and subgroup limits.",
    "study_design": "Identify design, species, setting and whether the evidence is primary research, synthesis, guideline, classical text or local experience.",
    "recommendation_strength": "Preserve conditional wording, intended use and recommendation strength; do not infer it from agreement.",
    "evidence_certainty": "Record certainty and appraisal method separately from recommendation strength or consensus; do not invent a grade.",
    "consensus": "Record agreement or voting only when reported; consensus is not an effect estimate or evidence certainty.",
    "causal_strength": "Check whether wording moves from association or mechanism to causal efficacy beyond the study design and supporting evidence.",
}


def review_packet(catalog):
    """Bind blank support worksheets to the exact registered evidence."""
    public = public_catalog(catalog)
    raw_sources = {s["id"]: s for s in catalog["sources"]}
    sources = {s["id"]: s for s in public["sources"]}
    items = []
    for claim in public["claims"]:
        source = sources[claim["source_id"]]
        passage = next(p for p in source["passages"] if p["id"] == claim["passage_id"])
        request = {"claim_id": claim["id"], "source_id": source["id"], "passage_id": passage["id"], "claim_text": claim["text"], "quote": passage["text"], "disease": claim["disease"]}
        items.append({
            "claim": copy.deepcopy(claim), "source_id": source["id"],
            "passage": passage,
            "binding_sha256": review_binding_hash(claim, raw_sources[source["id"]]),
            "checks": check_binding(catalog, request),
            "worksheet": {
                "verdict": "unassessed", "rationale": None,
                "reviewer": None, "reviewed_at": None,
                "additional_context_needed": None, "conflicting_evidence": None,
                "clinical_inference": {"assessment": "unassessed", "rationale": None},
                "dimensions": {key: {"assessment": "unassessed", "rationale": None, "evidence_locator": None, "guidance": DIMENSION_GUIDANCE[key]} for key in DIMENSIONS},
            },
        })
    return {
        "schema": "review-preparation-v1", "corpus_sha256": catalog_hash(catalog),
        "corpus_version": catalog["version"], "clinical_release": False,
        "purpose": "Blank human-review worksheets; not a clinical approval or model judgment.",
        "verdict_options": ["supported", "partially_supported", "contradicted", "insufficient_context", "irrelevant"],
        "dimension_options": ["matches", "mismatch", "not_reported", "not_applicable", "unassessed"],
        "verdict_definition": "Whether the cited source text supports the exact assertion, with scope and context preserved.",
        "clinical_inference_definition": "Separately assess whether the study design and certainty justify the proposed clinical inference. Use justified, overstated, insufficient_context, not_applicable or unassessed. This does not grant publication approval or establish patient applicability.",
        "review_rule": "Read the excerpt and required surrounding context. Explain each applicable dimension and not_applicable. Use unassessed when not yet checked; use not_reported only after checking the explicitly recorded source scope. Missing context may require insufficient_context. Distinguish source-text support from justified clinical inference, trial outcomes from recommendations, and certainty from consensus. Record conflicting evidence.",
        "sources": public["sources"], "items": items,
    }


def sanitized_receipt(catalog, operation, payload, result):
    """Persist only server-owned identifiers and enumerated gate results."""
    if operation == "search":
        bindings = [{"claim_id": m["claim"]["id"], "source_id": m["source"]["id"], "passage_id": m["passage"]["id"], "checks": m["checks"]} for m in result["references"]]
    elif operation == "audit-answer":
        return {
            "schema": "sanitized-answer-receipt-v1", "operation": operation,
            "status": result["status"], "corpus_sha256": catalog_hash(catalog),
            "clinical_release": False, "input_retained": False,
            "coverage": copy.deepcopy(result["coverage"]),
            "citation_summary": copy.deepcopy(result["citation_summary"]),
            "joint_support": result["joint_support"], "question_completeness": result["question_completeness"],
            "units": [{"id": u["id"], "status": u["status"], "reason": u["reason"], "citations": copy.deepcopy(u["citations"])} for u in result["units"]],
            "semantic_model": "not_run", "atomic_claim_extraction": "not_run",
            "limit": "Draft text, offsets and answer hashes are not retained. Unit counts do not measure semantic or clinical completeness. This receipt cannot reconstruct the draft answer.",
        }
    elif operation == "check":
        public = public_catalog(catalog)
        claim = next((c for c in public["claims"] if c["id"] == payload["claim_id"]), None)
        source = next((s for s in public["sources"] if s["id"] == payload["source_id"]), None)
        passage = next((p for p in source["passages"] if p["id"] == payload["passage_id"]), None) if source else None
        bindings = [{"claim_id": claim["id"] if claim else None, "source_id": source["id"] if source else None, "passage_id": passage["id"] if passage else None, "checks": copy.deepcopy(result)}]
    else:
        raise ValueError("unsupported_receipt_operation")
    return {
        "schema": "sanitized-receipt-v1", "operation": operation,
        "status": result["status"], "corpus_sha256": catalog_hash(catalog),
        "clinical_release": False, "bindings": bindings,
        "input_retained": False,
        "limit": "Submitted question, edited claim, quote and their hashes are not retained. Stored canonical evidence does not reconstruct submitted wording. This is an engineering receipt, not a clinical review.",
    }
