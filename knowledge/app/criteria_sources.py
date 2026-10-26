"""Source-bound complete classification table, distinct from clinical approval."""

import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from app.core import ROOT, parse_json
from app.fulltext import canonical_hash, file_hash, local_path

DEFAULT_BUNDLE = ROOT / "work/diagnosis-v0.16/criteria-bundle/index-final.json"
SOURCE_ID = "pmc-sjd-criteria-2016"
BUNDLE_ID = "sjd-acr-eular-2016-table3"
SOURCE_URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC5650478/"
SOURCE_HTML = "work/diagnosis-v0.16/source-acquisition/criteria-pmc.html"
SOURCE_CORE = "work/diagnosis-v0.16/source-acquisition/criteria-core.json"
TRUSTED_HTML_SHA256 = "4968b40df84745da6836286cd4177ef10b1f8f03618b3187a632ce6406e93427"
TRUSTED_CORE_SHA256 = "af330b590541db94266ee825709f205ef080754c1652d998c44ee1140ac14e38"
MAX_HTML_BYTES = 2_000_000
MAX_BLOCK = 1600
REQUIRED_IDS = ("T3", "P74", "P75", "P76", "P84", "P85", "P86")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
QUALITY_NOTE = (
    "Deterministic transcription of original PMC author-manuscript HTML Table 3. "
    "All five rows, weights, total-score threshold, inclusion/exclusion conditions "
    "and five footnotes are retained together. Footnote callout anchors are omitted "
    "from prose and recorded separately; genuine squared-area superscript is retained. "
    "This is an HTML table, not OA JATS or a PDF page. Format/coverage review is not "
    "clinical approval, independent diagnostic validation or a current-version guarantee."
)


class _Node:
    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", [])
        self.stack = [self.root]
        self.count = 0

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 15000 or len(self.stack) > 80:
            raise ValueError("criteria_html_structure_limit")
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                return

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def _text(node):
    if node.tag in {"script", "style", "noscript"}:
        return ""
    if node.tag == "a" and node.attrs.get("href", "").startswith("#TFN"):
        return ""
    value = "".join(_text(child) if isinstance(child, _Node) else child for child in node.children)
    if node.tag == "sup" and value.strip() == "2":
        return "\u00b2"
    if node.tag == "li":
        return "\n- " + value + "\n"
    return value


def _plain(node):
    return re.sub(r"\s+", " ", _text(node)).strip()


def _parse(raw):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_HTML_BYTES or b"<!ENTITY" in raw.upper():
        raise ValueError("invalid_criteria_html")
    parser = _Parser()
    try:
        parser.feed(raw.decode("utf-8"))
        parser.close()
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid_criteria_html") from error
    all_nodes = list(parser.root.walk())
    nodes = {}
    for key in REQUIRED_IDS:
        matches = [node for node in all_nodes if node.attrs.get("id") == key]
        if len(matches) != 1:
            raise ValueError("criteria_dom_id_missing_or_duplicate")
        nodes[key] = matches[0]
    table_nodes = list(nodes["T3"].walk())
    if any(nodes[key] not in table_nodes for key in REQUIRED_IDS[1:]):
        raise ValueError("criteria_qualification_outside_table")
    meta = {}
    for name in ("citation_title", "citation_pmid", "citation_doi", "citation_fulltext_html_url"):
        values = [node.attrs.get("content") for node in all_nodes if node.tag == "meta" and node.attrs.get("name") == name]
        if len(values) != 1 or not isinstance(values[0], str) or not values[0]:
            raise ValueError("criteria_metadata_missing_or_duplicate")
        meta[name] = values[0]
    if (meta["citation_pmid"] != "27785888" or meta["citation_doi"] != "10.1002/art.39859"
            or meta["citation_fulltext_html_url"] != SOURCE_URL):
        raise ValueError("criteria_html_identity_mismatch")
    rows = []
    links = [{"dom_id": "P74", "target": node.attrs["href"]} for node in nodes["P74"].walk()
        if node.tag == "a" and node.attrs.get("href", "").startswith("#TFN")]
    for row in table_nodes:
        if row.tag == "tr":
            cells = [child for child in row.children if isinstance(child, _Node) and child.tag in {"td", "th"}]
            if len(cells) != 2 or any(child.attrs.get("rowspan", "1") != "1" or child.attrs.get("colspan", "1") != "1" for child in cells):
                raise ValueError("unsupported_criteria_table_cells")
            rows.append([_plain(cell) for cell in cells])
            links.extend({"row": len(rows) - 1, "target": node.attrs["href"]}
                for cell in cells for node in cell.walk()
                if node.tag == "a" and node.attrs.get("href", "").startswith("#TFN"))
    if len(rows) != 6 or rows[0] != ["Item", "Weight / Score"] or [row[1] for row in rows[1:]] != ["3", "3", "1", "1", "1"]:
        raise ValueError("criteria_table_shape_changed")
    footnotes = [node.attrs.get("id") for node in table_nodes if node.attrs.get("id", "").startswith("TFN")]
    if footnotes != ["TFN6", "TFN7", "TFN8", "TFN9", "TFN10"]:
        raise ValueError("criteria_footnote_coverage_changed")
    qualification_nodes = {key: _plain(nodes[key]) for key in REQUIRED_IDS[1:]}
    if any(not value for value in qualification_nodes.values()):
        raise ValueError("empty_criteria_qualification")
    heading = next((node for node in table_nodes if node.tag == "h4"), None)
    if heading is None:
        raise ValueError("criteria_table_heading_missing")
    # Keep table weights paired with their row and their unit-defining footnotes.
    table_text = qualification_nodes["P74"] + "\n\n" + "\n".join(" | ".join(row) for row in rows)
    table_text += "\n\n" + "\n\n".join(qualification_nodes[key] for key in ("P84", "P85", "P86"))
    blocks = [
        ("criteria_and_methods", ["T3", "P74", "P84", "P85", "P86"], table_text),
        ("inclusion", ["P75"], qualification_nodes["P75"]),
        ("exclusion_and_medication_note", ["P76"], qualification_nodes["P76"]),
    ]
    if any(not 12 <= len(text) <= MAX_BLOCK for _, _, text in blocks):
        raise ValueError("criteria_required_block_exceeds_budget")
    return meta, _plain(heading), blocks, links


def build_criteria_bundle(html_path=SOURCE_HTML, core_path=SOURCE_CORE):
    """Only the reviewed original bytes may create this version of the bundle."""
    html_file, core_file = local_path(html_path), local_path(core_path)
    if html_file.stat().st_size > MAX_HTML_BYTES or core_file.stat().st_size > MAX_HTML_BYTES:
        raise ValueError("criteria_source_size_limit")
    if file_hash(html_file) != TRUSTED_HTML_SHA256 or file_hash(core_file) != TRUSTED_CORE_SHA256:
        raise ValueError("criteria_source_integrity_failure")
    core = parse_json(core_file.read_text(encoding="utf-8"))
    try:
        records = core["resultList"]["result"]
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError("criteria_core_identity_mismatch")
        record = records[0]
        if (record["id"] != "27785888" or record["pmcid"] != "PMC5650478" or record["doi"] != "10.1002/art.39859"
                or record.get("source") != "MED" or record.get("authMan") != "Y"):
            raise ValueError("criteria_core_identity_mismatch")
    except (KeyError, TypeError) as error:
        raise ValueError("criteria_core_identity_mismatch") from error
    meta, table_heading, blocks, links = _parse(html_file.read_bytes())
    source = {
        "id": SOURCE_ID, "title": meta["citation_title"], "metadata_title": record["title"],
        "title_zh": "2016\u5e74ACR/EULAR\u539f\u53d1\u6027\u5e72\u71e5\u7efc\u5408\u5f81\u5206\u7c7b\u6807\u51c6\uff1a\u57fa\u4e8e\u4e09\u4e2a\u56fd\u9645\u60a3\u8005\u961f\u5217\u7684\u5171\u8bc6\u4e0e\u6570\u636e\u9a71\u52a8\u65b9\u6cd5",
        "title_translation": "assistant_translation_unreviewed", "pmid": "27785888", "pmcid": "PMC5650478",
        "doi": "10.1002/art.39859", "disease": "sjd", "year": int(record["pubYear"]), "standard_year": 2016,
        "journal": record["journalInfo"]["journal"]["title"], "study_type": "classification_standard", "tcm_related": False,
        "source_url": SOURCE_URL, "evidence_kind": "html_section", "access": "local_fulltext_html",
        "html_path": html_file.relative_to(ROOT.resolve()).as_posix(), "html_sha256": TRUSTED_HTML_SHA256,
        "core_path": core_file.relative_to(ROOT.resolve()).as_posix(), "core_sha256": TRUSTED_CORE_SHA256,
        "source_version": "public_author_manuscript_html", "license": record.get("license"),
        "quality_note": QUALITY_NOTE, "identity_status": "source_html_metadata_identifiers_matched",
        "criteria_bundle_id": BUNDLE_ID, "criteria_complete": True, "question_scope": "classification_criteria",
        "review_status": "pending", "clinical_approval": None, "retrieval_eligible": True,
        "review_note": "\u88683\u53ca\u5168\u90e8\u811a\u6ce8\u5df2\u4f5c\u6765\u6e90\u683c\u5f0f\u4e0e\u8986\u76d6\u6838\u5bf9\uff0c\u5c1a\u672a\u83b7\u5f97\u4e34\u5e8a\u5ba1\u6279\u3002\u5206\u7c7b\u6807\u51c6\u4e0e\u4e34\u5e8a\u8bca\u65ad\u5206\u522b\u4f7f\u7528\uff1b\u6458\u8981\u4e2d\u7684\u75c5\u7406\u9762\u79ef\u5355\u4f4d\u7701\u7565\u95ee\u9898\u4ee5\u88683\u811a\u6ce8\u4e3a\u51c6\u4fdd\u7559\u8bb0\u5f55\u3002",
    }
    sections, chunks = [], []
    for order, (role, dom_ids, text) in enumerate(blocks, 1):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        section_id = "T3_" + role
        cid = "ft_" + hashlib.sha256(f"{TRUSTED_HTML_SHA256}:{section_id}:{digest}".encode()).hexdigest()[:24]
        locator = "Table 3 > " + role.replace("_", " ") + " (DOM " + ", ".join("#" + key for key in dom_ids) + ")"
        section = {"source_id": SOURCE_ID, "section_id": section_id, "locator": locator, "text": text,
            "text_sha256": digest, "html_table_id": "T3", "dom_ids": dom_ids, "evidence_kind": "html_section"}
        sections.append(section)
        chunks.append({"id": cid, "source_id": SOURCE_ID, "evidence_kind": "html_section", "pdf_page": None,
            "section_id": section_id, "locator": locator, "text": text, "text_sha256": digest,
            "section_text_sha256": digest, "section_start": 0, "section_end": len(text), "html_table_id": "T3",
            "criteria_bundle_id": BUNDLE_ID, "criteria_required": True, "criteria_order": order,
            "question_scope": "classification_criteria", "retrieval_eligible": True,
            "quality_note": QUALITY_NOTE, "clinical_approval": None})
    source["required_chunk_ids"] = [chunk["id"] for chunk in chunks]
    result = {"schema": "complete-criteria-html-bundle-v1", "version": "0.16.0", "data_origin": "real_public_documents",
        "clinical_release": False, "sources": [source], "sections": sections, "chunks": chunks,
        "table_heading": table_heading, "footnote_callout_links": links,
        "normalization": "Collapse whitespace; separate table cells with |; remove only TFN callout anchors while retaining all footnote text and reference numbers; convert genuine superscript 2 to Unicode squared symbol. Reorder method footnotes beside table rows; preserve inclusion and exclusion as separate required blocks."}
    result["sha256"] = canonical_hash(result)
    return result


def load_criteria_bundle(path=None):
    target = Path(path) if path is not None else DEFAULT_BUNDLE
    target = target.resolve()
    if not target.is_relative_to(ROOT.resolve()) or not target.is_file() or target.stat().st_size > 100000:
        raise ValueError("invalid_criteria_bundle_path")
    value = parse_json(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != "complete-criteria-html-bundle-v1":
        raise ValueError("invalid_criteria_bundle")
    try:
        source = value["sources"][0]
        rebuilt = build_criteria_bundle(source["html_path"], source["core_path"])
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError("invalid_criteria_bundle") from error
    if rebuilt != value:
        raise ValueError("criteria_source_text_binding_failure")
    return value


def render_section(source, section):
    """Render our normalized table transcription; never serve original HTML."""
    heading = "\u539f\u6587HTML\u8868\u683c\u53ca\u9650\u5b9a\u6761\u4ef6"
    note = "\u672c\u9875\u4e3a\u539f\u59cbPMC\u4f5c\u8005\u7a3f\u88683\u7684\u7ed3\u6784\u5316\u6587\u672c\uff0c\u4e0d\u662fPDF\u9875\u56fe\u3002\u8bf7\u5c06\u6761\u76ee\u3001\u6743\u91cd\u3001\u5165\u53e3\u6761\u4ef6\u3001\u6392\u9664\u6761\u4ef6\u548c\u811a\u6ce8\u4e00\u5e76\u9605\u8bfb\u3002"
    doc = ("<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>" + heading + "</title><body><main><h1>" + heading + "</h1><p>" + note + "</p><h2>" +
        html.escape(source["title"]) + "</h2><h3>" + html.escape(section["locator"]) + "</h3><pre style=\"white-space:pre-wrap\">" +
        html.escape(section["text"]) + "</pre><p><a rel=\"noopener noreferrer\" href=\"" + html.escape(SOURCE_URL + "#T3", quote=True) +
        "\">\u67e5\u770bPMC\u539f\u59cb\u88683</a></p></main></body></html>")
    return doc.encode("utf-8")
