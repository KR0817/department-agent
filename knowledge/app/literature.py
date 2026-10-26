"""Frozen JATS full texts with section provenance, separate from PDF pages."""

import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core import ROOT, parse_json
from app.fulltext import canonical_hash, file_hash, local_path

DEFAULT_SIDECAR = ROOT / "work/literature-v0.15/index.json"
MAX_XML_BYTES = 16_000_000
MAX_INDEX_BYTES = 160_000_000
MAX_SOURCES = 1000
MAX_CHUNKS = 60000
QUALITY_NOTE = (
    "Original JATS XML retained; body paragraph text is indexed by section. "
    "Table markup and figure/supplement references are retained as provided in XML; "
    "linked binary assets and supplements have not been acquired or interpreted. "
    "Tables are not interpreted as plain-text answer evidence. Section text is not a publisher PDF page. "
    "Clinical relevance, completeness, currency and approval remain unassessed."
)
SOURCE_FIELDS = (
    "id title pmid pmcid doi year journal disease study_type tcm_related source_url "
    "fulltext_url xml_path xml_sha256 core_path core_sha256 fulltext_bytes body_chars "
    "license status_flags query retrieved_at xml_identifiers identity_verified review_status"
).split()
SKIP_TAGS = {"table-wrap", "fig", "supplementary-material", "media", "ref-list", "disp-formula"}


def _text(node):
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def parse_article(raw, record):
    """Use local XML only; reject entity declarations and bound document size."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_XML_BYTES or b"<!ENTITY" in raw.upper():
        raise ValueError("invalid_jats_bytes")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, RecursionError) as error:
        raise ValueError("invalid_jats_xml") from error
    for node in root.iter():
        if isinstance(node.tag, str):
            node.tag = node.tag.rsplit("}", 1)[-1]
    if root.tag != "article":
        raise ValueError("invalid_jats_article")
    meta = root.find("./front/article-meta")
    body = root.find("./body")
    if meta is None or body is None:
        raise ValueError("missing_jats_body_or_metadata")
    identifiers = {node.get("pub-id-type"): _text(node) for node in meta.findall("article-id")}
    pmc = identifiers.get("pmc", identifiers.get("pmcid", ""))
    pmc = pmc if pmc.startswith("PMC") else "PMC" + pmc
    if not re.fullmatch(r"PMC[0-9]+", pmc) or pmc != record.get("pmcid"):
        raise ValueError("jats_identity_mismatch")
    for key in ("doi", "pmid"):
        if record.get(key) and identifiers.get(key) and str(record[key]).casefold() != identifiers[key].casefold():
            raise ValueError("jats_identity_mismatch")
    title = meta.find("./title-group/article-title")
    if title is None or _text(title) != record.get("title"):
        raise ValueError("jats_title_mismatch")
    sections = []
    omitted = {name: 0 for name in sorted(SKIP_TAGS)}

    def paragraph_blocks(node, depth=0):
        if depth > 40:
            raise ValueError("jats_content_depth_exceeded")
        blocks = []
        for child in node:
            if child.tag in SKIP_TAGS:
                omitted[child.tag] += 1
            elif child.tag == "sec" or child.tag in {"title", "label"}:
                continue
            elif child.tag == "p":
                # Do not splice an uninterpreted table/formula into a sentence.
                if any(desc.tag in SKIP_TAGS for desc in child.iter()):
                    for desc in child.iter():
                        if desc.tag in SKIP_TAGS:
                            omitted[desc.tag] += 1
                    continue
                text = _text(child)
                if text:
                    blocks.append(text)
            else:
                blocks.extend(paragraph_blocks(child, depth + 1))
        return blocks

    def visit(node, trail, depth=0):
        if depth > 30:
            raise ValueError("jats_section_depth_exceeded")
        heading = node.find("title")
        next_trail = trail + ([_text(heading)] if heading is not None and _text(heading) else [])
        blocks = paragraph_blocks(node)
        if blocks:
            text = "\n\n".join(blocks)
            if len(text) > 500000:
                raise ValueError("jats_section_too_large")
            number = len(sections) + 1
            sections.append({"section_id": f"sec_{number:04d}", "xml_section_id": node.get("id"),
                "locator": " > ".join(next_trail) or "Article body", "text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
        for child in node:
            if child.tag == "sec":
                visit(child, next_trail, depth + 1)

    visit(body, [])
    if not sections or sum(len(s["text"]) for s in sections) < 300:
        raise ValueError("insufficient_jats_body")
    return sections, omitted


def _spans(text):
    boundaries = sorted(set([0, len(text)] + [match.end() for match in
        re.finditer(r"\n\s*\n|[.!?\u3002\uff01\uff1f][\s\n]", text)]))
    start = 0
    while start < len(text):
        choices = [end for end in boundaries if start < end <= start + 2500]
        end = max(choices) if choices else next(end for end in boundaries if end > start)
        # An oversized sentence is retained in the section but never truncated.
        if end - start <= 12000 and text[start:end].strip():
            yield start, end
        start = end


def _record(record):
    if not isinstance(record, dict):
        raise ValueError("invalid_literature_record")
    if (not re.fullmatch(r"epmc-pmc[0-9]+", str(record.get("id", "")))
            or record.get("id") != "epmc-" + str(record.get("pmcid", "")).lower()
            or not isinstance(record.get("disease"), str) or record.get("disease") not in {"ra", "sjd", "gout"}
            or record.get("identity_verified") is not True
            or record.get("clinical_approval") is not None
            or record.get("review_status") != "pending"):
        raise ValueError("invalid_literature_identity_or_state")
    for key in ("title", "pmcid", "xml_path", "xml_sha256", "core_path", "core_sha256"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise ValueError("invalid_literature_metadata")
    if record.get("source_url") != "https://europepmc.org/articles/" + record["pmcid"]:
        raise ValueError("invalid_literature_source_url")
    flags = record.get("status_flags")
    if not isinstance(flags, dict) or flags.get("core_is_retracted") in (True, "Y"):
        raise ValueError("invalid_or_retracted_literature_state")
    source = {key: record.get(key) for key in SOURCE_FIELDS}
    source.update({"evidence_kind": "xml_section", "access": "local_fulltext_xml",
                   "quality_note": QUALITY_NOTE, "clinical_approval": None,
                   "review_note": flags.get("manual_review_note_zh"),
                   "identity_status": "metadata_xml_identifiers_matched"})
    return source


def _read_local_json(path, limit):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("invalid_literature_file")
    return path, parse_json(path.read_text(encoding="utf-8"))


def build_sidecar(manifest_path, titles_path=None, title_origin="local_model_unreviewed"):
    manifest_path, manifest = _read_local_json(manifest_path, MAX_INDEX_BYTES)
    if not isinstance(manifest, dict) or manifest.get("schema") != "public-literature-acquisition-v1":
        raise ValueError("invalid_acquisition_manifest")
    records = manifest.get("records")
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_SOURCES:
        raise ValueError("invalid_literature_inventory")
    titles, titles_record = {}, None
    if title_origin not in {"local_model_unreviewed", "assistant_translation_unreviewed"}:
        raise ValueError("invalid_title_origin")
    if titles_path is not None:
        titles_path, titles = _read_local_json(titles_path, 2_000_000)
        if not isinstance(titles, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                or not 2 <= len(v) <= 3000 for k, v in titles.items()):
            raise ValueError("invalid_title_translations")
        titles_record = {"path": titles_path.relative_to(ROOT.resolve()).as_posix(), "sha256": file_hash(titles_path), "origin": title_origin}
    sources, sections, chunks, seen = [], [], [], {key: set() for key in ("id", "pmid", "pmcid", "doi")}
    for record in records:
        source = _record(record)
        sid = source["id"]
        for key, values in seen.items():
            value = str(source.get(key) or "").casefold()
            if value and value in values:
                raise ValueError("duplicate_literature_identity")
            if value:
                values.add(value)
        xml = local_path(source["xml_path"])
        core = local_path(source["core_path"])
        if xml.suffix.lower() != ".xml" or core.suffix.lower() != ".json":
            raise ValueError("invalid_literature_carrier")
        if xml.stat().st_size > MAX_XML_BYTES or core.stat().st_size > 2_000_000:
            raise ValueError("literature_source_too_large")
        raw = xml.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["xml_sha256"] or file_hash(core) != source["core_sha256"]:
            raise ValueError("literature_source_integrity_failure")
        if len(raw) != source.get("fulltext_bytes"):
            raise ValueError("literature_source_size_mismatch")
        core_record = parse_json(core.read_text(encoding="utf-8"))
        if not isinstance(core_record, dict) or core_record.get("pmcid") != source["pmcid"]:
            raise ValueError("literature_core_identity_mismatch")
        for key in ("pmid", "doi"):
            identity = core_record.get(key)
            if key == "pmid" and not identity and core_record.get("source") == "MED":
                identity = core_record.get("id")
            if source.get(key) and str(identity or "").casefold() != str(source[key]).casefold():
                raise ValueError("literature_core_identity_mismatch")
        article_sections, omitted = parse_article(raw, source)
        source["omitted_from_text_index"] = omitted
        if sid in titles:
            source.update(title_zh=titles[sid], title_translation=title_origin)
        for section in article_sections:
            section = {"source_id": sid, **section}
            sections.append(section)
            for start, end in _spans(section["text"]):
                text = section["text"][start:end]
                cid = "ft_" + hashlib.sha256(
                    f"{source['xml_sha256']}:{section['section_id']}:{start}:{end}:{section['text_sha256']}".encode()
                ).hexdigest()[:24]
                chunks.append({"id": cid, "source_id": sid, "evidence_kind": "xml_section", "pdf_page": None,
                    "section_id": section["section_id"], "locator": section["locator"], "text": text,
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "section_text_sha256": section["text_sha256"],
                    "section_start": start, "section_end": end,
                    "retrieval_eligible": not bool(source["status_flags"].get("retrieval_block_reason")),
                    "quality_note": QUALITY_NOTE, "clinical_approval": None})
        source["retrieval_eligible"] = any(c["source_id"] == sid and c["retrieval_eligible"] for c in chunks)
        sources.append(source)
    if not chunks or len(chunks) > MAX_CHUNKS:
        raise ValueError("invalid_literature_chunk_count")
    if not set(titles).issubset(seen["id"]):
        raise ValueError("unknown_title_translation_id")
    result = {"schema": "public-jats-index-v1", "version": "0.15.0", "data_origin": "real_public_documents",
        "clinical_release": False, "acquisition_manifest": manifest_path.relative_to(ROOT.resolve()).as_posix(),
        "acquisition_sha256": file_hash(manifest_path), "title_translations": titles_record,
        "sources": sources, "sections": sections, "chunks": chunks}
    result["sha256"] = canonical_hash(result)
    return result


def load_sidecar(path=None):
    """Rebuild the source binding once at startup; stored text cannot self-certify."""
    target, value = _read_local_json(path or DEFAULT_SIDECAR, MAX_INDEX_BYTES)
    if (not isinstance(value, dict) or value.get("schema") != "public-jats-index-v1"
            or value.get("data_origin") != "real_public_documents" or value.get("clinical_release") is not False
            or value.get("sha256") != canonical_hash({k: v for k, v in value.items() if k != "sha256"})):
        raise ValueError("invalid_literature_index")
    manifest = local_path(value.get("acquisition_manifest"))
    if file_hash(manifest) != value.get("acquisition_sha256"):
        raise ValueError("literature_register_integrity_failure")
    titles = value.get("title_translations")
    titles_path = None
    if titles is not None:
        if not isinstance(titles, dict):
            raise ValueError("invalid_title_provenance")
        titles_path = local_path(titles.get("path"))
        if file_hash(titles_path) != titles.get("sha256"):
            raise ValueError("title_translation_integrity_failure")
    rebuilt = build_sidecar(manifest, titles_path, titles.get("origin", "local_model_unreviewed") if titles else "local_model_unreviewed")
    if rebuilt != value:
        raise ValueError("literature_source_text_binding_failure")
    return value


def render_section(source, section):
    """A safe local reading view of parsed XML text, never a claimed PDF image."""
    title = html.escape(source["title"])
    locator = html.escape(section["locator"])
    body = "\n".join("<p>" + html.escape(paragraph) + "</p>" for paragraph in section["text"].split("\n\n"))
    heading = "\u539f\u6587 XML \u7ae0\u8282"
    note = "\u672c\u9875\u5c55\u793a\u5df2\u4fdd\u5b58 XML \u7684\u7ae0\u8282\u6b63\u6587\uff0c\u4e0d\u662f\u51fa\u7248\u793e PDF \u9875\u56fe\u3002\u8868\u683c\u3001\u56fe\u548c\u8865\u5145\u6750\u6599\u9700\u56de\u539f\u7ad9\u6838\u5bf9\u3002"
    document = ("<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>" + heading + "</title><body><main><h1>" + heading + "</h1><p>" + note + "</p><h2>" + title +
        "</h2><h3>" + locator + "</h3><p>PMCID " + html.escape(source["pmcid"]) + "</p>" + body +
        "<p><a rel=\"noopener noreferrer\" href=\"" + html.escape(source["source_url"], quote=True) + "\">"
        "\u67e5\u770b\u539f\u59cb\u5168\u6587\u9875\u9762</a></p></main></body></html>")
    return document.encode("utf-8")
