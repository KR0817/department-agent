"""Reuse a pinned, reviewed aggregate release without opening clinical inputs."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit
import zipfile

from . import __version__
from .dashboard import DashboardError, HTML_TEMPLATE
from .dashboard_sources import build_source_dashboard
from .dashboard_layout import refine_local_layout
from .dashboard_network import enhance_network
from .dashboard_threeui import enhance_community_ui
from .dashboard_followup import enhance_followup
from .dashboard_network_3d import enhance_network_3d
from .dashboard_network_compare import enhance_network_compare
from .dashboard_group_matrix import enhance_group_matrix
from .privacy import FORBIDDEN_PUBLIC_HEADERS


ARTIFACTS = frozenset({"index.html", "research-report.html", "conditional_retention.csv",
    "disease-change-results.csv", "literature-analysis-results.csv", "source-ledger.json",
    "supplement.html", "analysis-report.md", "robots.txt", "source-correction.json"})
TABLES = ("groups", "summaries", "items", "combinations", "changes", "longitudinal",
          "comparisons", "yearSummaries", "yearItems", "yearChanges")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract_payload(page: str, element: str) -> dict:
    matches = re.findall(r'<script id="' + re.escape(element) + r'" type="application/json">(.*?)</script>', page, re.S)
    if len(matches) != 1:
        raise DashboardError("Expected exactly one reviewed aggregate JSON block")
    try:
        value = json.loads(matches[0])
    except ValueError as error:
        raise DashboardError("Invalid reviewed aggregate JSON") from error
    if not isinstance(value, dict):
        raise DashboardError("Reviewed payload must be an object")
    return value


def validate_payload(payload: dict) -> None:
    """Bounded structural check; this does not certify general anonymity."""
    if not set(TABLES) <= set(payload) or any(not isinstance(payload[key], list) for key in TABLES):
        raise DashboardError("Reviewed aggregate tables are missing or malformed")
    if any(not isinstance(row, dict) for key in TABLES for row in payload[key]):
        raise DashboardError("Reviewed aggregate rows must be objects")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("synthetic_mode") is not False:
        raise DashboardError("Original aggregate provenance must declare synthetic_mode=false")
    threshold = provenance.get("min_public_n")
    if type(threshold) is not int or threshold < 10:
        raise DashboardError("Original aggregate threshold must be at least ten")
    if payload.get("clinicalMode") is not True or not isinstance(payload.get("research"), dict):
        raise DashboardError("Reviewed clinical/research structure is unavailable")
    if any(not isinstance(rows, list) for rows in payload["research"].values()):
        raise DashboardError("Research fields must be aggregate lists")
    def walk(value):
        if isinstance(value, dict):
            if any(str(key).casefold() in FORBIDDEN_PUBLIC_HEADERS for key in value):
                raise DashboardError("Patient-level field is not allowed in this local aggregate view")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str):
            if re.search(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b", value):
                raise DashboardError("Exact dates are not allowed in aggregate payloads")
            if re.search(r"[A-Za-z]:[\\/]", value):
                raise DashboardError("Local paths are not allowed in aggregate payloads")
    walk(payload)


def load_reviewed_release(release: Path, contract: dict) -> tuple[dict[str, dict], dict]:
    """Read only ten allowlisted artifacts and the release's hash manifest."""
    expected = contract.get("artifacts", {})
    if not isinstance(expected, dict) or set(expected) != ARTIFACTS:
        raise DashboardError("Reviewed source contract must contain the fixed artifact allowlist")
    if any(not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest) for digest in expected.values()):
        raise DashboardError("Malformed reviewed artifact digest")
    recorded = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    if recorded.get("artifacts") != expected:
        raise DashboardError("Recorded release differs from the pinned source contract")
    actual = {name: sha256(release / "public" / name) for name in sorted(expected)}
    if actual != expected:
        raise DashboardError("Reviewed artifact hash mismatch")
    page = (release / "public/index.html").read_text(encoding="utf-8")
    if set(contract.get("payloads", {})) != {"primary", "supplement"}:
        raise DashboardError("Both reviewed source contracts are required")
    payloads = {}
    for source, element in (("primary", "dashboard-data"), ("supplement", "supplement-data")):
        pinned = contract["payloads"][source]
        if pinned.get("element_id") != element:
            raise DashboardError("Unexpected reviewed JSON block")
        payload = extract_payload(page, element)
        validate_payload(payload)
        if payload_hash(payload) != pinned.get("sha256"):
            raise DashboardError("Reviewed aggregate payload mismatch")
        if any(payload["provenance"].get(key) != pinned.get(key) for key in ("dataset_id", "cohort_version", "synthetic_mode")):
            raise DashboardError("Reviewed source identity mismatch")
        if {group["code"]: group["patients"] for group in payload["groups"]} != pinned.get("groups"):
            raise DashboardError("Reviewed group denominator mismatch")
        payloads[source] = payload
    return payloads, actual


class LocalLinks(HTMLParser):
    """Keep existing user-clicked references while rejecting automatic requests."""
    def __init__(self, available: set[str]):
        super().__init__()
        self.available = available

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key not in {"href", "src"} or not value:
                continue
            url = urlsplit(value)
            if url.scheme in {"http", "https"}:
                if key == "src" or tag == "link":
                    raise DashboardError("Automatic external resource is not allowed")
            elif url.scheme or url.netloc:
                raise DashboardError("Unsupported local link scheme")
            elif url.path and unquote(url.path) not in self.available:
                raise DashboardError("Unpackaged local link")


def deterministic_zip(directory: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.iterdir()):
            if path.is_file():
                info = zipfile.ZipInfo(path.name, (2026, 10, 23, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())


def build_reviewed_dashboard(release: Path, output: Path, contract: dict, *, inheritance_frozen: Path | None = None) -> dict:
    """Render original aggregates with current interactions and no new analyses."""
    payloads, source_hashes = load_reviewed_release(release, contract)
    inheritance_page = None
    inheritance_summary = None
    if inheritance_frozen is not None:
        from .inheritance import build_view, read_frozen, template_bundle
        from .dashboard_inheritance import render_inheritance
        bundle = read_frozen(inheritance_frozen)
        if bundle["synthetic"] is not True:
            raise DashboardError("Only explicitly synthetic cases can accompany an aggregate delivery")
        view = build_view(bundle)
        inheritance_page = render_inheritance(bundle, view)
        inheritance_summary = {"synthetic": True, "content_sha256": view["validation"]["content_sha256"],
                               "clinical_validation": False}
    output.mkdir(parents=True, exist_ok=False)
    public = output / "local"
    public.mkdir()
    intermediate = output / "reviewed_inputs"
    intermediate.mkdir()
    for key, payload in payloads.items():
        view = deepcopy(payload)
        view["presentation"] = {"local_aggregate_only": True, "renderer_version": __version__,
            "reviewed_release": contract["reviewed_release"], "original_payload_sha256": payload_hash(payload)}
        encoded = json.dumps(view, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("&", "\\u0026")
        page = HTML_TEMPLATE.replace("__TITLE__", "MingYiRx").replace("__PAYLOAD__", encoded)
        (intermediate / f"{key}.html").write_text(page, encoding="utf-8")
    metadata = {
        "primary": {"title": "\u539f\u59cb\u95e8\u8bca\u6c47\u603b", "scope": "\u539f\u59cb CSV \u6765\u6e90\uff1b\u4fdd\u7559\u539f\u5206\u6790\u53e3\u5f84\u4e0e\u8bcd\u5178\u3002"},
        "supplement": {"title": "\u8865\u5145\u95e8\u8bca\u6c47\u603b", "scope": "\u8865\u5145\u5f3a\u76f4\u6027\u810a\u67f1\u708e\u6765\u6e90\uff1b2026 \u5e74\u4e3a\u5df2\u6709\u90e8\u5206\u5e74\u5ea6\u8bb0\u5f55\uff0c\u4eba\u6570\u4e0d\u52a0\u5165\u4e3b\u6765\u6e90\u3002"}
    }
    build_source_dashboard(intermediate / "primary.html", intermediate / "supplement.html", public / "index.html",
        refresh_template=True, source_metadata=metadata, default_source="primary")
    page = (public / "index.html").read_text(encoding="utf-8")
    notice = ('<aside class="policy-note" id="original-context"><b>\u539f\u95e8\u8bca\u6c47\u603b\u00b7\u672c\u5730\u4ea4\u4e92\u7248</b>'
        '<p>\u4f7f\u7528 2026-09-30 \u7edf\u4e00\u7248\u7684\u5df2\u6838\u5bf9\u6c47\u603b\u7ed3\u679c\u3002\u836f\u5473\u3001\u514b\u6570\u548c\u6bd4\u4f8b\u6cbf\u7528\u539f\u503c\uff1b\u672a\u5c55\u793a\u9879\u4fdd\u7559\u4e3a\u4e0d\u53ef\u7528\u3002\u5171\u75c5\u6807\u7b7e\u4e0e\u836f\u5473\u5171\u73b0\u5206\u522b\u89e3\u91ca\u3002</p>'
        '<a href="research-report.html">\u539f\u6587\u732e\u89e3\u8bfb</a> · <a href="analysis-report.md">\u539f\u6765\u6e90\u4e0e\u5206\u6790\u8bf4\u660e</a></aside>')
    page = page.replace('<main class="main">', '<main class="main">' + notice, 1)
    page = page.replace('</head>', '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer"></head>', 1)
    page = refine_local_layout(page)
    page = enhance_network(page)
    page = enhance_followup(page)
    page = enhance_community_ui(page)
    page = enhance_network_3d(page)
    page = enhance_network_compare(page)
    page = enhance_group_matrix(page)
    if inheritance_page is not None:
        link = ('<aside class="policy-note" id="inheritance-entry"><b>\u540d\u533b\u7ecf\u9a8c\u4e0e\u4f20\u627f\u5de5\u4f5c\u53f0</b>'
                '<p>\u6309\u6765\u6e90\u6838\u9a8c\u3001\u590d\u8bca\u5bf9\u7167\u3001\u5bfc\u5e08\u6279\u6ce8\u3001\u76f8\u4f3c\u533b\u6848\u548c\u6559\u5b66\u6f14\u7ec3\u987a\u5e8f\u4f7f\u7528\u3002</p>'
                '<a href="inheritance.html">\u6253\u5f00\u4f20\u627f\u5de5\u4f5c\u53f0\uff08\u5408\u6210\u5f00\u53d1\u6837\u4f8b\uff09</a></aside>')
        page, inserted = re.subn(r'(<main\b[^>]*>)', lambda match: match[1] + link, page, count=1)
        if inserted != 1:
            raise DashboardError("Expected one main workspace for the inheritance entry")
        (public / "inheritance.html").write_text(inheritance_page, encoding="utf-8", newline="\n")
        (public / "inheritance-template.json").write_text(
            json.dumps(template_bundle(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    (public / "index.html").write_text(page, encoding="utf-8")
    preservation = {}
    for key, element in (("primary", "dashboard-data"), ("supplement", "supplement-data")):
        rendered = extract_payload(page, element)
        rendered.pop("presentation", None)
        rendered.pop("source_identity", None)
        preservation[key] = rendered == payloads[key]
        if not preservation[key]:
            raise DashboardError("Original aggregate values changed during rendering")
    for name in sorted(ARTIFACTS - {"index.html"}):
        shutil.copyfile(release / "public" / name, public / name)
    (public / "README.txt").write_text(
        "MingYiRx original aggregate local workbench\nOpen index.html directly. No server is required.\n"
        "Original reviewed aggregate results, not synthetic results. No raw clinical inputs are included.\n"
        "The two sources retain independent denominators. This delivery was not published online.\n"
        "Historical research-report.html and supporting files are copied unchanged.\n"
        "Existing aggregate suppression is preserved; this is not a new public anonymity certification.\n", encoding="utf-8")
    available = {p.name for p in public.iterdir()}
    for path in public.glob("*.html"):
        LocalLinks(available).feed(path.read_text(encoding="utf-8"))
    zip_path = output / "mingyirx-original-local.zip"
    deterministic_zip(public, zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != available:
            raise DashboardError("Local archive verification failed")
    result = {"gate": "PASS_WITH_WARNINGS", "renderer_version": __version__,
        "contract_version": contract["contract_version"], "reviewed_release": contract["reviewed_release"],
        "source_artifact_hashes": source_hashes,
        "original_payload_hashes": {key: payload_hash(value) for key, value in payloads.items()},
        "payloads_preserved": preservation, "synthetic": False,
        "raw_inputs_read": False, "statistics_recomputed": False, "new_intersections": False,
        "public_deployment": False, "source_patients_pooled": False,
        "scope": "Local reuse of previously reviewed aggregate release; no new public privacy certification",
        "files": {p.name: sha256(p) for p in sorted(public.iterdir()) if p.is_file()},
        "zip_sha256": sha256(zip_path)}
    if inheritance_summary is not None:
        result["inheritance_workspace"] = inheritance_summary
    (output / "build-manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
