"""Bounded criteria coverage policy, not a general medical entailment verifier."""
import re
import unicodedata

CRITERIA_INTENTS = {"diagnostic_criteria", "classification_criteria", "mixed_criteria"}


def normalized_text(text):
    return "".join(char for char in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(char))


def question_intent(question):
    text = normalized_text(question)
    classification = bool(re.search(r"\u5206\u7c7b\u6807\u51c6|classification\s+criteria", text))
    diagnosis = bool(re.search(
        r"\u8bca\u65ad\u6807\u51c6|\u8bca\u65ad\u4f9d\u636e|\u786e\u8bca\u6807\u51c6|\u786e\u8bca\u6761\u4ef6|"
        r"(?:\u5982\u4f55|\u600e\u6837|\u600e\u4e48).{0,12}(?:\u8bca\u65ad|\u786e\u8bca)|"
        r"diagnostic\s+criteria|diagnosis\s+criteria|criteria\s+for\s+(?:the\s+)?diagnosis", text))
    tcm = bool(re.search(r"\u4e2d\u533b|\u8fa8\u8bc1|\u8bc1\u5019|\u8bc1\u578b|\btcm\b|syndrome\s+differentiation", text))
    if tcm:
        if classification or (diagnosis and re.search(r"\u897f\u533b|\u751f\u7269\u533b\u5b66|biomedical", text)):
            return "mixed_criteria"
        return "tcm_syndrome"
    if classification:
        return "classification_criteria"
    return "diagnostic_criteria" if diagnosis else "general"


def requested_disease(question):
    text = normalized_text(question)
    patterns = {"sjd": r"\u5e72\u71e5\u7efc\u5408\u5f81|sjogren|\bsjd\b",
                "ra": r"\u7c7b\u98ce\u6e7f|rheumatoid|\bra\b",
                "gout": r"\u75db\u98ce|\bgout\b"}
    matches = [key for key, pattern in patterns.items() if re.search(pattern, text)]
    return matches[0] if len(matches) == 1 else "multiple" if matches else None


def complete_group(candidates, sources):
    """Require the whole source-bound group; keywords cannot establish coverage."""
    if not candidates or len({c["source_id"] for c in candidates}) != 1:
        return None
    source = sources[candidates[0]["source_id"]]
    required = source.get("required_chunk_ids")
    bundle = source.get("criteria_bundle_id")
    if (source.get("criteria_complete") is not True or source.get("question_scope") != "classification_criteria"
            or not isinstance(bundle, str) or not bundle or not isinstance(required, list)
            or not 1 <= len(required) <= 3 or any(not isinstance(cid, str) for cid in required)
            or len(set(required)) != len(required)):
        return None
    chunks = {c["id"]: c for c in candidates}
    if set(chunks) != set(required):
        return None
    if any(c.get("criteria_bundle_id") != bundle or c.get("criteria_required") is not True
           or c.get("retrieval_eligible") is not True or c.get("question_scope") != "classification_criteria"
           or not 12 <= len(c["text"]) <= 1600 for c in chunks.values()):
        return None
    return [chunks[cid] for cid in required]


def criteria_candidates(index, question, disease, source_id, limit):
    """A complete standard is required; never replace it with enrollment/TCM text."""
    if question_intent(question) == "mixed_criteria":
        return []
    requested = requested_disease(question)
    if requested == "multiple" or (requested and disease != "all" and disease != requested):
        return []
    selected_sources = [s for s in index["sources"] if source_id == "all" or s["id"] == source_id]
    target = requested or (disease if disease != "all" else selected_sources[0]["disease"] if source_id != "all" else None)
    if target is None:
        return []
    years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", question))
    source_map = {s["id"]: s for s in selected_sources}
    for source in sorted(selected_sources, key=lambda s: (-int(s.get("standard_year") or 0), s["id"])):
        if source["disease"] != target or (years and years != {str(source.get("standard_year"))}):
            continue
        candidates = [c for c in index["chunks"] if c["source_id"] == source["id"] and c.get("criteria_required") is True]
        complete = complete_group(candidates, source_map)
        if complete is not None and len(complete) <= limit:
            return [{**chunk, "retrieval_basis": "complete_source_bundle", "retrieval_score": 1.0} for chunk in complete]
    return []
