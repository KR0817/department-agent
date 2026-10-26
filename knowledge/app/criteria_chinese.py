"""Versioned Chinese rendering bound to the complete original criteria table."""

import copy
import hashlib
from pathlib import Path

from app.benchmark import exact_fields
from app.chinese import _translation_checks
from app.core import ROOT, parse_json
from app.criteria_sources import load_criteria_bundle

TRANSLATION_PATH = ROOT / "data/criteria_zh_v016.json"
TRUSTED_TRANSLATION_SHA256 = "074af5013a4210b19af55ed9f4c2f6fb2a3febff73d2fdacd52c645c71dd1cab"
TRUSTED_BUNDLE_SHA256 = "e5e9f34033d769cd716229c0014f8ff6756f4938d063ab4bd8712f9c7495896c"
ORIGIN = "versioned_assistant_translation"
REVIEW_STATUS = "pending_clinician_review"


def _load_translations(bundle):
    target = Path(TRANSLATION_PATH).resolve()
    if not target.is_relative_to(ROOT.resolve()) or not target.is_file() or target.stat().st_size > 65536:
        raise ValueError("invalid_criteria_translation_path")
    raw = target.read_bytes()
    if hashlib.sha256(raw).hexdigest() != TRUSTED_TRANSLATION_SHA256:
        raise ValueError("criteria_translation_integrity_failure")
    value = parse_json(raw.decode("utf-8"))
    exact_fields(value, "schema version source_id criteria_bundle_id bundle_sha256 source_html_sha256 source_core_sha256 origin review_status clinical_approval required_chunk_ids items")
    source = bundle["sources"][0]
    expected = {
        "schema": "versioned-criteria-translation-v1", "version": "0.16.0", "source_id": source["id"],
        "criteria_bundle_id": source["criteria_bundle_id"], "bundle_sha256": bundle["sha256"],
        "source_html_sha256": source["html_sha256"], "source_core_sha256": source["core_sha256"],
        "origin": ORIGIN, "review_status": REVIEW_STATUS, "clinical_approval": None,
        "required_chunk_ids": source["required_chunk_ids"],
    }
    if any(value[key] != expected_value for key, expected_value in expected.items()):
        raise ValueError("criteria_translation_metadata_mismatch")
    if not isinstance(value["items"], list) or len(value["items"]) != 3:
        raise ValueError("incomplete_criteria_translation")
    translated = {}
    for item, chunk in zip(value["items"], bundle["chunks"]):
        exact_fields(item, "chunk_id source_quote_sha256 answer_zh")
        if item["chunk_id"] != chunk["id"] or item["source_quote_sha256"] != chunk["text_sha256"]:
            raise ValueError("criteria_translation_quote_mismatch")
        text = item["answer_zh"]
        if not isinstance(text, str) or not 2 <= len(text) <= 5000:
            raise ValueError("invalid_criteria_translation_text")
        translated[chunk["id"]] = {"answer_zh": text, "translation_checks": _translation_checks(chunk["text"], text)}
    return translated


def translate_criteria_extracts(excerpts):
    """Accept every original block exactly; do not translate arbitrary passages."""
    if not isinstance(excerpts, list) or len(excerpts) != 3:
        raise ValueError("incomplete_criteria_extracts")
    bundle = load_criteria_bundle()
    if bundle.get("sha256") != TRUSTED_BUNDLE_SHA256:
        raise ValueError("criteria_translation_bundle_mismatch")
    source = bundle["sources"][0]
    chunks = {chunk["id"]: chunk for chunk in bundle["chunks"]}
    translations = _load_translations(bundle)
    seen = set()
    for item in excerpts:
        if not isinstance(item, dict) or item.get("source_id") != source["id"]:
            raise ValueError("invalid_criteria_excerpt_source")
        cid = item.get("chunk_id")
        if not isinstance(cid, str) or cid not in chunks or cid in seen:
            raise ValueError("invalid_criteria_excerpt_coverage")
        chunk = chunks[cid]
        if item.get("quote") != chunk["text"] or item.get("quote_sha256") != chunk["text_sha256"]:
            raise ValueError("criteria_excerpt_quote_mismatch")
        if item.get("clinical_approval") is not None:
            raise ValueError("unearned_criteria_clinical_approval")
        expected_metadata = {key: source[key] for key in ("pmid", "pmcid", "doi", "title", "title_zh", "evidence_kind", "criteria_bundle_id")}
        expected_metadata.update(locator=chunk["locator"], pdf_page=None, quote_start=0, quote_end=len(chunk["text"]))
        if any(key in item and item[key] != expected for key, expected in expected_metadata.items()):
            raise ValueError("criteria_excerpt_metadata_mismatch")
        seen.add(cid)
    if seen != set(source["required_chunk_ids"]):
        raise ValueError("incomplete_criteria_extracts")
    result = copy.deepcopy(excerpts)
    for item in result:
        item.update(translations[item["chunk_id"]])
        item.update(translation_status="versioned_translation", translation_origin=ORIGIN,
            translation_review_status=REVIEW_STATUS, clinical_approval=None,
            translation_artifact_sha256=TRUSTED_TRANSLATION_SHA256,
            translation_bundle_sha256=TRUSTED_BUNDLE_SHA256)
    return {"extracts": result, "translation_status": "complete", "translation_model_called": False,
        "translation_error": None, "clinical_approval": None}
