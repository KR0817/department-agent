"""Validate provenance without claiming automated medical entailment."""

import copy
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DISEASES = {"all", "ra", "sjd", "gout"}
SOURCE_STATES = {"active", "retracted", "corrected_unreviewed", "unavailable"}
RISK_WORDS = (
    "\u5242\u91cf", "\u505c\u836f", "\u6362\u836f", "\u5b55", "\u598a\u5a20",
    "\u5904\u65b9", "\u52a0\u51cf", "\u5408\u7528", "\u809d\u529f\u80fd",
    "\u80be\u529f\u80fd", "\u6025\u75c7", "\u51fa\u8840", "\u591a\u5c11\u6beb\u514b",
    "dose", "pregnan", "prescri", "stop medication", "mg", "interaction",
)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def require_text(value, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("invalid_text")
    value.encode("utf-8")
    return value


def only_fields(value, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed.split()):
        raise ValueError("unexpected_fields")


def require_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("invalid_date")
    date.fromisoformat(value)


def parse_json(raw):
    """Reject ambiguous object keys rather than silently trusting the last one."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("non_finite_number")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)


def review_binding_hash(claim, source):
    """Pin a review to the exact assertion, source identity, excerpt and scope."""
    passage = next((p for p in source["passages"] if p["id"] == claim["passage_id"]), None)
    binding = {"schema": 2, "text": claim["text"], "disease": claim["disease"], "category": claim.get("category"), "source": {k: v for k, v in source.items() if k not in {"passages", "status", "currency"}}, "passage": passage}
    return digest(json.dumps(binding, sort_keys=True, ensure_ascii=True))


def validate_catalog(payload):
    """Reject malformed imports; this does not certify their medical content."""
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("invalid_catalog")
    if not isinstance(payload.get("claims"), list):
        raise ValueError("invalid_claims")
    only_fields(payload, "version curated_at scope sources claims")
    if len(payload["sources"]) > 500 or len(payload["claims"]) > 5000:
        raise ValueError("catalog_too_large")
    if "curated_at" in payload:
        require_date(payload["curated_at"])
    if "scope" in payload:
        require_text(payload["scope"])
    require_text(payload.get("version"), 50)
    sources = {}
    for source in payload["sources"]:
        if not isinstance(source, dict):
            raise ValueError("invalid_source")
        only_fields(source, "id title disease year pmid doi url origin access status currency verified_at verification_scope passages online_date")
        sid = require_text(source.get("id"), 100)
        if sid in sources:
            raise ValueError("duplicate_source")
        for field in ("title", "verified_at", "verification_scope", "access"):
            require_text(source.get(field))
        require_date(source["verified_at"])
        if "online_date" in source:
            require_date(source["online_date"])
        if source.get("disease") not in DISEASES - {"all"}:
            raise ValueError("invalid_disease")
        if source.get("origin") not in {"public", "synthetic"}:
            raise ValueError("invalid_origin")
        if source.get("status") not in SOURCE_STATES:
            raise ValueError("invalid_source_status")
        if source.get("currency") not in {"unknown", "current", "superseded"}:
            raise ValueError("invalid_currency")
        if type(source.get("year")) is not int or not 1900 <= source["year"] <= 2100:
            raise ValueError("invalid_year")
        parts = urlsplit(require_text(source.get("url")))
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("invalid_source_url")
        if source.get("pmid") is not None and (not isinstance(source["pmid"], str) or not re.fullmatch(r"[1-9][0-9]{0,9}", source["pmid"])):
            raise ValueError("invalid_pmid")
        if source.get("doi") is not None and (not isinstance(source["doi"], str) or not re.fullmatch(r"10\.\d{4,9}/\S+", source["doi"])):
            raise ValueError("invalid_doi")
        passages = source.get("passages")
        if not isinstance(passages, list) or not 1 <= len(passages) <= 100:
            raise ValueError("missing_passages")
        seen = set()
        for passage in passages:
            if not isinstance(passage, dict):
                raise ValueError("invalid_passage")
            only_fields(passage, "id text locator context_note")
            pid = require_text(passage.get("id"), 100)
            if pid in seen:
                raise ValueError("duplicate_passage")
            seen.add(pid)
            require_text(passage.get("text"), 20000)
            require_text(passage.get("locator"))
            if "context_note" in passage:
                require_text(passage["context_note"])
        sources[sid] = source
    seen = set()
    for claim in payload["claims"]:
        if not isinstance(claim, dict):
            raise ValueError("invalid_claim")
        only_fields(claim, "id text source_id passage_id disease review reviewer reviewed_at reviewed_binding_sha256 category tags")
        cid = require_text(claim.get("id"), 100)
        if cid in seen:
            raise ValueError("duplicate_claim")
        seen.add(cid)
        require_text(claim.get("text"))
        require_text(claim.get("source_id"), 100)
        require_text(claim.get("passage_id"), 100)
        source = sources.get(claim.get("source_id"))
        if not source or claim.get("passage_id") not in {p["id"] for p in source["passages"]}:
            raise ValueError("broken_binding")
        if claim.get("disease") != source["disease"]:
            raise ValueError("invalid_claim_scope")
        if claim.get("review") not in {"pending", "approved", "rejected"}:
            raise ValueError("invalid_review")
        if claim["review"] == "approved":
            require_text(claim.get("reviewer"), 200)
            require_text(claim.get("reviewed_at"), 50)
            if claim.get("reviewed_binding_sha256") != review_binding_hash(claim, source):
                raise ValueError("stale_review_binding")
        for field in ("reviewer", "reviewed_at", "reviewed_binding_sha256", "category"):
            if claim.get(field) is not None:
                require_text(claim[field], 200)
        if not isinstance(claim.get("tags"), list) or not 1 <= len(claim["tags"]) <= 100:
            raise ValueError("missing_tags")
        for tag in claim["tags"]:
            require_text(tag, 100)
    return payload


def load_catalog(path=None):
    path = Path(path) if path else ROOT / "data" / "corpus.json"
    return validate_catalog(parse_json(path.read_text(encoding="utf-8")))


def public_catalog(catalog):
    result = copy.deepcopy(catalog)
    result["sources"] = [s for s in result["sources"] if s["origin"] == "public"]
    ids = {s["id"] for s in result["sources"]}
    result["claims"] = [c for c in result["claims"] if c["source_id"] in ids]
    for source in result["sources"]:
        for passage in source["passages"]:
            passage["sha256"] = digest(passage["text"])
    return result


def catalog_hash(catalog):
    return digest(json.dumps(catalog, sort_keys=True, ensure_ascii=True))


def check_binding(catalog, request):
    """Check a registered pair, never infer support for an arbitrary new claim."""
    required = {"claim_id", "source_id", "passage_id", "claim_text", "quote", "disease"}
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError("invalid_check_request")
    for key in required:
        require_text(request[key], {"quote": 20000, "claim_text": 8000}.get(key, 4000))
    if request["disease"] not in DISEASES:
        raise ValueError("invalid_disease")
    claim = next((c for c in catalog["claims"] if c["id"] == request["claim_id"]), None)
    source = next((s for s in catalog["sources"] if s["id"] == request["source_id"]), None)
    passage = next((p for p in source["passages"] if p["id"] == request["passage_id"]), None) if source else None
    canonical = bool(claim and request["claim_text"] == claim["text"])
    pair = bool(claim and source and claim["source_id"] == source["id"] and claim["passage_id"] == request["passage_id"])
    quote = bool(passage and request["quote"] == passage["text"])
    public_ids = {s["id"] for s in catalog["sources"] if s["origin"] == "public"}
    different_registered = pair and not canonical and any(
        c["source_id"] in public_ids and c["text"] == request["claim_text"] for c in catalog["claims"]
    )
    reviewed = bool(claim and source and pair and claim["review"] == "approved" and claim.get("reviewer") and claim.get("reviewed_at") and claim.get("reviewed_binding_sha256") == review_binding_hash(claim, source))
    scope = bool(claim and source and request["disease"] == claim["disease"] == source["disease"])
    checks = []

    def add(name, state, reason):
        checks.append({"name": name, "state": state, "reason": reason})

    add("source_identity", "pass" if source else "fail", "catalog_record_found" if source else "unknown_source")
    add("source_usable", "pass" if source and source["status"] == "active" else "fail", "active_source" if source and source["status"] == "active" else "unusable_source")
    add("passage_integrity", "pass" if quote else "fail", "exact_excerpt" if quote else "excerpt_mismatch")
    # Registry identity is checkable; a mismatch does not infer semantic irrelevance.
    if pair and canonical:
        add("registered_binding", "pass", "registered_pair")
    elif different_registered:
        add("registered_binding", "fail", "different_registered_claim")
    else:
        add("registered_binding", "unknown" if pair else "fail", "unreviewed_wording" if pair else "binding_mismatch")
    add("clinical_support", "pass" if reviewed and pair and canonical and quote else "unknown", "human_review_record" if reviewed and pair and canonical and quote else "human_review_required")
    add("disease_scope", "pass" if scope else ("unknown" if request["disease"] == "all" else "fail"), "scope_matches" if scope else "scope_not_confirmed")
    currency = source["currency"] if source else "unknown"
    add("currency", "pass" if currency == "current" else ("fail" if currency == "superseded" else "unknown"), "currency_checked" if currency == "current" else ("currency_superseded" if currency == "superseded" else "currency_not_confirmed"))
    add("provenance", "pass" if source and source["origin"] == "public" else "fail", "public_source" if source and source["origin"] == "public" else "synthetic_or_unknown")
    if claim and claim["review"] == "rejected":
        add("review_decision", "fail", "claim_rejected")
    states = {c["state"] for c in checks}
    status = "blocked" if "fail" in states else ("review_required" if "unknown" in states else "eligible")
    return {"status": status, "checks": checks, "semantic_model": "not_run", "patient_applicability": "not_evaluated", "clinical_release": False, "eligible_reference": status == "eligible"}


def terms(text):
    normalized = text.casefold()
    words = set(re.findall(r"[a-z0-9]+", normalized))
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
    return words


def search(catalog, request):
    if not isinstance(request, dict) or set(request) != {"question", "disease", "mode"}:
        raise ValueError("invalid_search_request")
    question = require_text(request["question"], 1000).strip()
    disease, mode = request["disease"], request["mode"]
    if disease not in DISEASES or mode not in {"reference", "answer"}:
        raise ValueError("invalid_search_options")
    risk = any(word in question.casefold() for word in RISK_WORDS)
    query_terms = terms(question)
    sources = {s["id"]: s for s in public_catalog(catalog)["sources"]}
    matches = []
    for claim in catalog["claims"]:
        source = sources.get(claim["source_id"])
        if not source or source["status"] != "active" or source["currency"] == "superseded":
            continue
        if disease != "all" and claim["disease"] != disease:
            continue
        # ponytail: lexical ranking is a small-corpus baseline; benchmark recall before adding embeddings.
        text = " ".join([source["title"], claim["text"], *claim["tags"]])
        score = len(query_terms & terms(text))
        if not score:
            continue
        passage = next(p for p in source["passages"] if p["id"] == claim["passage_id"])
        checked = check_binding(catalog, {"claim_id": claim["id"], "source_id": source["id"], "passage_id": passage["id"], "claim_text": claim["text"], "quote": passage["text"], "disease": disease})
        matches.append({"claim": claim, "source": source, "passage": passage, "checks": checked, "rank_score": score})
    matches.sort(key=lambda item: (-item["rank_score"], item["claim"]["id"]))
    matches = matches[:6]
    eligible = [m for m in matches if m["checks"]["eligible_reference"] and not risk]
    status = "references_found" if matches else "no_evidence"
    if mode == "answer":
        status = "review_required" if matches else "no_evidence"
        if risk:
            status = "high_risk_review"
        elif eligible:
            status = "reviewed_references"
    return {"status": status, "references": matches, "claims": [m["claim"] for m in eligible] if mode == "answer" else [], "risk_flag": risk, "risk_screen": "keyword_baseline_not_validated", "clinical_release": False, "limitations": ["small_corpus", "no_semantic_model", "no_patient_applicability"]}
