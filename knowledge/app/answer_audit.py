"""Account for all draft text without pretending to extract clinical claims."""

from app.core import DISEASES, RISK_WORDS, catalog_hash, check_binding, require_text

LIMITS = {
    "semantic_model": "not_run", "atomic_claim_extraction": "not_run",
    "patient_applicability": "not_evaluated", "clinical_release": False,
    "joint_support": "not_evaluated", "question_completeness": "not_evaluated",
}


def split_answer(answer):
    """Return code-point spans; punctuation units are not atomic propositions."""
    require_text(answer, 8000)
    units = []
    start = 0

    def emit(end):
        left, right = start, end
        while left < right and answer[left].isspace():
            left += 1
        while right > left and answer[right - 1].isspace():
            right -= 1
        if right > left:
            units.append({"id": f"u{len(units) + 1}", "start": left, "end": right, "text": answer[left:right]})
            if len(units) > 80:
                raise ValueError("too_many_units")

    # ponytail: punctuation coverage is conservative; benchmark atomic extraction separately.
    for index, char in enumerate(answer):
        boundary = char in "\u3002\uff01\uff1f\uff1b;\n\r"
        boundary = boundary or (char in ".!?" and (index + 1 == len(answer) or answer[index + 1].isspace()))
        if boundary:
            emit(index + 1)
            start = index + 1
    emit(len(answer))
    return units


def segment_answer(catalog, request):
    if not isinstance(request, dict) or set(request) != {"answer", "disease"}:
        raise ValueError("invalid_segment_request")
    if require_text(request["disease"], 20) not in DISEASES:
        raise ValueError("invalid_disease")
    units = split_answer(request["answer"])
    public_ids = {s["id"] for s in catalog["sources"] if s["origin"] == "public"}
    for unit in units:
        unit["suggested_claim_ids"] = [c["id"] for c in catalog["claims"] if c["source_id"] in public_ids and c["text"] == unit["text"] and (request["disease"] == "all" or c["disease"] == request["disease"])]
    return {**LIMITS, "units": units, "corpus_sha256": catalog_hash(catalog), "segmentation": "punctuation_baseline_not_atomic_claim_extraction"}


def audit_answer(catalog, request):
    """Check every unit and every unique citation; no reference majority vote."""
    if not isinstance(request, dict) or set(request) != {"answer", "disease", "corpus_sha256", "bindings"}:
        raise ValueError("invalid_answer_audit")
    segmented = segment_answer(catalog, {key: request[key] for key in ("answer", "disease")})
    if request["corpus_sha256"] != segmented["corpus_sha256"]:
        raise ValueError("stale_corpus")
    bindings = request["bindings"]
    if not isinstance(bindings, list) or len(bindings) > len(segmented["units"]):
        raise ValueError("invalid_bindings")
    unit_ids = {unit["id"] for unit in segmented["units"]}
    assigned = {}
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {"unit_id", "citations"}:
            raise ValueError("invalid_unit_binding")
        unit_id = require_text(binding["unit_id"], 10)
        if unit_id not in unit_ids or unit_id in assigned:
            raise ValueError("duplicate_or_unknown_unit")
        citations = binding["citations"]
        if not isinstance(citations, list) or len(citations) > 8:
            raise ValueError("invalid_citations")
        for citation in citations:
            if not isinstance(citation, dict) or set(citation) != {"claim_id", "source_id", "passage_id"}:
                raise ValueError("invalid_citation")
            for value in citation.values():
                require_text(value, 100)
        assigned[unit_id] = citations

    sources = {s["id"]: s for s in catalog["sources"] if s["origin"] == "public"}
    claims = {c["id"]: c for c in catalog["claims"] if c["source_id"] in sources}
    public = {**catalog, "sources": list(sources.values()), "claims": list(claims.values())}
    units = []
    duplicate_count = 0
    for unit in segmented["units"]:
        citations, seen = [], set()
        for link in assigned.get(unit["id"], []):
            triple = tuple(link[key] for key in ("claim_id", "source_id", "passage_id"))
            if triple in seen:
                duplicate_count += 1
                continue
            seen.add(triple)
            source = sources.get(link["source_id"])
            passage = next((p for p in source["passages"] if p["id"] == link["passage_id"]), None) if source else None
            checked = check_binding(public, {**link, "claim_text": unit["text"], "quote": passage["text"] if passage else "UNAVAILABLE_EXCERPT", "disease": request["disease"]})
            citations.append({
                "claim_id": link["claim_id"] if link["claim_id"] in claims else None,
                "source_id": source["id"] if source else None,
                "passage_id": passage["id"] if passage else None,
                "checks": checked,
            })
        states = {citation["checks"]["status"] for citation in citations}
        status = "blocked" if not citations or "blocked" in states else ("review_required" if "review_required" in states else "eligible_reference_only")
        units.append({**unit, "citations": citations, "status": status, "reason": "uncited_unit" if not citations else "all_citations_checked"})

    coverage = {
        "total_units": len(units), "cited_units": sum(bool(u["citations"]) for u in units),
        "uncited_units": sum(not u["citations"] for u in units),
        "blocked_units": sum(u["status"] == "blocked" for u in units),
        "review_required_units": sum(u["status"] == "review_required" for u in units),
        "duplicate_citations": duplicate_count,
    }
    citations = [citation for unit in units for citation in unit["citations"]]
    citation_summary = {"total": len(citations)}
    for status in ("blocked", "review_required", "eligible"):
        key = "eligible_reference" if status == "eligible" else status
        citation_summary[key] = sum(c["checks"]["status"] == status for c in citations)
    for state in ("pass", "fail", "unknown"):
        citation_summary["registered_binding_" + state] = sum(
            check["name"] == "registered_binding" and check["state"] == state
            for citation in citations for check in citation["checks"]["checks"]
        )
    risk = any(word in request["answer"].casefold() for word in RISK_WORDS)
    status = "blocked" if coverage["blocked_units"] else ("review_required" if coverage["review_required_units"] or risk else "eligible_reference_only")
    return {**LIMITS, "status": status, "units": units, "coverage": coverage, "citation_summary": citation_summary, "risk_flag": risk, "risk_screen": "keyword_baseline_not_validated", "segmentation": segmented["segmentation"], "corpus_sha256": segmented["corpus_sha256"]}
