"""Local public-document index and transparent bounded lexical retrieval."""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from app.core import ROOT, parse_json
from app.answerability import CRITERIA_INTENTS, criteria_candidates, normalized_text, question_intent

DEFAULT_INDEX = ROOT / "work/fulltext-v0.13/index.json"
MAX_CANDIDATE_CHARS = 12000
TRUSTED_SOURCE_HASHES = {
    "acr-ra-2021-acr": "7a00596c0e84ffb7188369e809faa9c89104fd429c7e7461fb5088f689f60148",
    "acr-gout-2020-acr": "9cd9facb2d02da25b507fd0de21fe31ad7928140f44881761aa52ff2f32b7a3d",
    "bsr-sjd-2024-birmingham-vor": "3ba51a159c19ab5bf02140813a8aff97b944b724c3c1e48e9871103a76a2779b",
    "tcm-gout-rbx-rct-2020": "36f74c14fbbdf1f86efd11440b420210074cda528b39b4fb1772be0513ac1765",
    "tcm-sjd-bqrz-rct-2023": "1a9becb7d5cab7661115a087f7a174da9f9d24832ffd9d41d1402b7c5c6a07eb",
    "tcm-sjd-pattern-consensus-2023": "76e14b95cd53bf65393518dc41e3f8621717d161835ea9690d5ffd3a9db3857a",
    "tcm-ra-guideline-2025": "3b75b06912412c6fddfa667860bdd346a8ece931bff14b34ad50370a680b6558",
    "acr-gout-erratum-2021": "a1f397179e6395b5714d496f2dea869659969699b4413f905eedc799cf7cd4b9",
}
SYNONYMS = {
    "\u53e3\u5e72": "dry mouth xerostomia salivary saliva",
    "\u773c\u5e72": "dry eye ocular schirmer tear",
    "\u6cea\u6db2": "schirmer tear lacrimal",
    "\u553e\u6db2": "salivary saliva flow",
    "\u5e72\u71e5\u7efc\u5408\u5f81": "sjogren sjogren's sjogren's syndrome sjd",
    "\u7c7b\u98ce\u6e7f": "rheumatoid arthritis",
    "\u75db\u98ce": "gout urate",
    "\u8bca\u65ad": "diagnosis diagnostic criteria",
    "\u5206\u7c7b\u6807\u51c6": "classification criteria eligibility exclusions score threshold",
    "\u8bca\u65ad\u6807\u51c6": "diagnostic classification criteria score threshold inclusion exclusion",
    "\u5c3f\u9178": "urate uric acid",
    "\u7f9f\u6c2f\u55b9": "hydroxychloroquine hcq",
    "\u7532\u6c28\u8776\u5464": "methotrexate",
    "\u5b89\u5168": "safety adverse harms",
    "\u4e0d\u826f\u53cd\u5e94": "adverse events safety",
    "\u4e0d\u826f\u4e8b\u4ef6": "adverse events safety",
    "\u526f\u4f5c\u7528": "adverse events safety",
    "\u6709\u6548": "efficacy effective results",
    "\u7597\u6548": "efficacy outcome results",
    "\u7ec4\u95f4": "between groups difference",
    "\u968f\u673a": "randomized randomised allocation",
    "\u7814\u7a76\u8bbe\u8ba1": "design randomized randomised multicenter multicentre double blind controlled",
    "\u591a\u4e2d\u5fc3": "multicenter multicentre",
    "\u53cc\u76f2": "double blind blinded",
    "\u5bf9\u7167": "control comparator placebo",
    "\u8054\u5408": "combination combined concomitant",
    "\u7597\u7a0b": "duration weeks treatment",
    "\u8bc1\u636e": "evidence certainty quality",
    "\u5171\u8bc6": "consensus voting agreement",
    "\u8865\u80be\u6e05\u70ed\u6da6\u71e5": "bushen qingre runzao bqrz",
    "\u70ed\u75f9\u6d88": "rebixiao rbx",
    "\u80be\u529f\u80fd": "renal kidney creatinine",
    "\u809d\u529f\u80fd": "hepatic liver enzymes",
}
STOP = set("the a an and or of to in is are was were for on with how what does do can could should from this that results study trial reported patients patient".split())
CLINICAL_FOCUS = set("efficacy effective effectiveness safety adverse event effect benefit harm risk outcome response mortality pain function dose dosage duration symptom severity remission improvement".split())


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_path(value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("invalid_index_path")
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError("index_path_outside_workspace")
    return path


def load_index(path=None):
    """Validate complete input bytes once when the application loads its index."""
    target = Path(path) if path is not None else DEFAULT_INDEX
    target = target.resolve()
    if not target.is_relative_to(ROOT.resolve()) or target.stat().st_size > 16_000_000:
        raise ValueError("invalid_index_file")
    raw = parse_json(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != "public-fulltext-index-v1" or raw.get("data_origin") != "real_public_documents" or raw.get("clinical_release") is not False:
        raise ValueError("invalid_fulltext_provenance")
    claimed_hash = raw.get("sha256")
    if claimed_hash != canonical_hash({k: v for k, v in raw.items() if k != "sha256"}):
        raise ValueError("index_digest_mismatch")
    sources, chunks = raw.get("sources"), raw.get("chunks")
    if not isinstance(sources, list) or not isinstance(chunks, list) or not sources or not chunks or len(chunks) > 5000:
        raise ValueError("invalid_index_inventory")
    source_ids, chunk_ids, checked_images = set(), set(), {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("invalid_source_record")
        sid = source.get("id")
        if not isinstance(sid, str) or sid in source_ids or sid not in TRUSTED_SOURCE_HASHES or source.get("pdf_sha256") != TRUSTED_SOURCE_HASHES[sid]:
            raise ValueError("untrusted_or_duplicate_source")
        if not isinstance(source.get("disease"), str) or source["disease"] not in {"ra", "sjd", "gout"} or source.get("clinical_approval") is not None:
            raise ValueError("invalid_source_state")
        for field in ("title", "quality_note", "pdf_path"):
            if not isinstance(source.get(field), str) or not source[field]:
                raise ValueError("invalid_source_metadata")
        pdf = local_path(source["pdf_path"])
        if pdf.suffix.lower() != ".pdf" or file_hash(pdf) != source["pdf_sha256"] or not pdf.read_bytes().startswith(b"%PDF-"):
            raise ValueError("source_integrity_failure")
        source_ids.add(sid)
    pages = raw.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("missing_page_records")
    page_map = {}
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("source_id"), str) or type(page.get("pdf_page")) is not int:
            raise ValueError("invalid_page_record")
        key = (page.get("source_id"), page.get("pdf_page"))
        if key in page_map or key[0] not in source_ids or type(key[1]) is not int or key[1] < 1:
            raise ValueError("invalid_page_record")
        if not isinstance(page.get("text"), str) or hashlib.sha256(page["text"].encode()).hexdigest() != page.get("text_sha256"):
            raise ValueError("page_text_integrity_failure")
        page_map[key] = page
    for chunk in chunks:
        if not isinstance(chunk, dict) or not isinstance(chunk.get("id"), str) or not isinstance(chunk.get("source_id"), str) or not re.fullmatch(r"ft_[a-f0-9]{24}", chunk["id"]) or chunk["id"] in chunk_ids or chunk["source_id"] not in source_ids:
            raise ValueError("invalid_chunk_identity")
        text = chunk.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_CANDIDATE_CHARS or hashlib.sha256(text.encode()).hexdigest() != chunk.get("text_sha256"):
            raise ValueError("chunk_text_integrity_failure")
        if type(chunk.get("pdf_page")) is not int or chunk["pdf_page"] < 1 or type(chunk.get("retrieval_eligible")) is not bool:
            raise ValueError("invalid_page_or_eligibility")
        page = page_map.get((chunk["source_id"], chunk["pdf_page"]))
        start, end = chunk.get("page_start"), chunk.get("page_end")
        if page is None or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(page["text"]):
            raise ValueError("invalid_page_text_offsets")
        if page["text"][start:end] != text or page["text_sha256"] != chunk.get("page_text_sha256"):
            raise ValueError("chunk_page_binding_failure")
        if any(chunk.get(k) != page.get(k) for k in ("image_path", "image_sha256")):
            raise ValueError("chunk_image_binding_failure")
        if chunk.get("clinical_approval") is not None or not isinstance(chunk.get("quality_note"), str):
            raise ValueError("invalid_chunk_review_state")
        image = local_path(chunk.get("image_path"))
        if image.suffix.lower() != ".png":
            raise ValueError("invalid_page_image")
        if image not in checked_images:
            content = image.read_bytes()
            if not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("invalid_page_image")
            checked_images[image] = hashlib.sha256(content).hexdigest()
        if checked_images[image] != chunk.get("image_sha256"):
            raise ValueError("page_image_integrity_failure")
        chunk_ids.add(chunk["id"])
    return raw


def tokens(text):
    words = []
    for token in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", normalized_text(text)):
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            words.extend(token[i:i+2] for i in range(len(token)-1))
        elif token not in STOP and len(token) > 1:
            words.append(token[:-1] if len(token) > 4 and token.endswith("s") else token)
    return words


def _with_criteria(index, enabled):
    from app.criteria_sources import DEFAULT_BUNDLE, load_criteria_bundle
    if not enabled or not DEFAULT_BUNDLE.exists():
        return index
    criteria = load_criteria_bundle()
    for source in criteria["sources"]:
        if any(any(source.get(key) and str(source[key]).casefold() == str(old.get(key) or "").casefold()
                   for key in ("id", "pmid", "pmcid", "doi")) for old in index["sources"]):
            raise ValueError("duplicate_criteria_source")
    result = {**index, "schema": "public-fulltext-combined-v1", "version": "0.16.0",
              "sources": index["sources"] + criteria["sources"],
              "sections": index.get("sections", []) + criteria["sections"],
              "chunks": index["chunks"] + criteria["chunks"],
              "criteria_index_sha256": criteria["sha256"]}
    result["sha256"] = canonical_hash({key: value for key, value in result.items() if key != "sha256"})
    return result


def load_combined_index(sidecar_path=None, *, include_criteria=True):
    """Keep the original PDF trust contract; add independently bound XML bodies."""
    from app.literature import DEFAULT_SIDECAR, load_sidecar
    pdf = load_index()
    target = Path(sidecar_path) if sidecar_path is not None else DEFAULT_SIDECAR
    if not target.exists():
        if sidecar_path is not None:
            raise ValueError("missing_literature_sidecar")
        return _with_criteria(pdf, include_criteria)
    xml = load_sidecar(target)
    known = {key: {str(source.get(key) or "").casefold() for source in pdf["sources"]
                   if source.get(key)} for key in ("id", "doi", "pmid", "pmcid")}
    added, duplicates = [], []
    for source in xml["sources"]:
        if any(str(source.get(key) or "").casefold() in values for key, values in known.items() if source.get(key)):
            duplicates.append(source["id"])
            continue
        added.append(source)
        for key, values in known.items():
            if source.get(key):
                values.add(str(source[key]).casefold())
    ids = {source["id"] for source in added}
    result = {**pdf, "schema": "public-fulltext-combined-v1", "version": "0.15.0",
              "sources": pdf["sources"] + added,
              "chunks": pdf["chunks"] + [chunk for chunk in xml["chunks"] if chunk["source_id"] in ids],
              "sections": [section for section in xml["sections"] if section["source_id"] in ids],
              "pdf_index_sha256": pdf["sha256"], "xml_index_sha256": xml["sha256"],
              "duplicate_xml_sources": duplicates}
    result["sha256"] = canonical_hash({key: value for key, value in result.items() if key != "sha256"})
    return _with_criteria(result, include_criteria)


def retrieve(index, question, disease="all", source_id="all", limit=8):
    """Lexical ranking only; no positive result without an overlapping term."""
    if not isinstance(question, str) or not question.strip() or len(question) > 1000 or not isinstance(disease, str) or disease not in {"all", "ra", "sjd", "gout"} or not isinstance(source_id, str) or type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError("invalid_retrieval_request")
    sources = {s["id"]: s for s in index["sources"]}
    if source_id != "all" and source_id not in sources:
        raise ValueError("unknown_fulltext_source")
    if question_intent(question) in CRITERIA_INTENTS:
        return criteria_candidates(index, question, disease, source_id, limit)
    expanded = question + " " + " ".join(value for key,value in SYNONYMS.items() if key in question)
    query = set(tokens(expanded))
    if source_id != "all":
        # Source selection already resolves the title; rank the remaining question.
        # Keep clinical intent even when it also occurs in the selected title.
        contextual = set(tokens(sources[source_id]["title"])) - CLINICAL_FOCUS
        if "\u7814\u7a76\u8bbe\u8ba1" in question or re.search(r"\b(?:study|trial|research)\s+design\b", question, re.I):
            # Design terms in the title can also be the explicit question intent.
            contextual -= set(tokens(SYNONYMS["\u7814\u7a76\u8bbe\u8ba1"]))
        focused = query - contextual
        if focused:
            query = focused
    if not query:
        return []
    candidates = [c for c in index["chunks"] if c.get("retrieval_eligible", False)
        and (source_id == "all" or c["source_id"] == source_id)
        and (disease == "all" or sources[c["source_id"]]["disease"] == disease)]
    counts = [Counter(tokens(c["text"])) for c in candidates]
    df = Counter(t for terms in counts for t in terms if t in query)
    average = sum(sum(c.values()) for c in counts) / max(len(counts), 1)
    ranked = []
    for chunk, terms in zip(candidates, counts):
        common = query & terms.keys()
        if not common:
            continue
        length = sum(terms.values())
        score = sum(math.log(1 + (len(counts)-df[t]+0.5)/(df[t]+0.5)) *
                    (terms[t]*2.2)/(terms[t]+1.2*(0.25+0.75*length/max(average,1))) for t in common)
        ranked.append((score, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
    selected, used = [], 0
    for score, chunk in ranked:
        if len(selected) == limit:
            break
        if used + len(chunk["text"]) > MAX_CANDIDATE_CHARS:
            continue
        selected.append({**chunk, "retrieval_score": round(score, 6)})
        used += len(chunk["text"])
    return selected
