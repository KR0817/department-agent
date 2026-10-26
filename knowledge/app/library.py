"""Public literature inventory, separate from clinical claims and approvals."""

import re
from urllib.parse import quote, urlsplit


def _doi(value):
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", (value or "").strip(), flags=re.I).lower()


def _source_url(source):
    value = source.get("source_url") or source.get("url")
    if value:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            return value
    if source.get("pmcid") and re.fullmatch(r"PMC[0-9]+", source["pmcid"]):
        return "https://pmc.ncbi.nlm.nih.gov/articles/" + source["pmcid"] + "/"
    if source.get("pmid") and re.fullmatch(r"[0-9]+", source["pmid"]):
        return "https://pubmed.ncbi.nlm.nih.gov/" + source["pmid"] + "/"
    if _doi(source.get("doi")).startswith("10."):
        return "https://doi.org/" + quote(_doi(source["doi"]), safe="/")
    return None


def public_inventory(fulltext, clinical):
    """Project an allowlist and deduplicate publications, never create claims."""
    sources, seen = [], set()
    for source, is_fulltext in [(s, True) for s in fulltext.get("sources", [])] + [(s, False) for s in clinical.get("sources", [])]:
        keys = {("id", source["id"])}
        for field in ("pmid", "pmcid", "doi"):
            value = _doi(source.get(field)) if field == "doi" else source.get(field)
            if value:
                keys.add((field, value))
        if keys & seen:
            seen.update(keys)
            continue
        seen.update(keys)
        xml = source.get("evidence_kind") == "xml_section"
        html = source.get("evidence_kind") == "html_section"
        eligible = is_fulltext and source.get("retrieval_eligible", True) is True
        locator = source.get("locator_url")
        if not isinstance(locator, str) or not re.fullmatch(r"/api/fulltext/(?:section|page)/ft_[a-f0-9]{24}", locator):
            locator = None
        item = {key: source.get(key) for key in ("id", "title", "title_zh", "pmid", "pmcid", "doi", "year", "journal", "disease", "study_type")}
        item.update(
            tcm_related=source.get("tcm_related") is True or source["id"].startswith("tcm-"),
            source_url=_source_url(source), access="fulltext_html" if is_fulltext and html else "fulltext_xml" if is_fulltext and xml else "fulltext_pdf" if is_fulltext else "abstract_only",
            review_status="pending", clinical_approval=None,
            fulltext_source_id=source["id"] if eligible else None, retrieval_eligible=eligible,
            locator_url=locator if is_fulltext else None,
            identity_status=source.get("identity_status") or ("source_file_verified" if is_fulltext else "registered_metadata"),
            title_translation=source.get("title_translation"),
            review_note=source.get("review_note"),
        )
        sources.append(item)
    return {"version": "v0.16", "answer_language": "zh-CN", "sources": sources,
            "counts": {"total": len(sources), "fulltext": sum(s["access"] != "abstract_only" for s in sources),
                       "indexed": sum(s["retrieval_eligible"] for s in sources), "clinical_approved": 0}}
