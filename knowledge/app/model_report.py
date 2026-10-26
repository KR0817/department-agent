"""Create a self-contained offline review; never promote a model label to approval."""

import argparse
import html
import json
import re
from pathlib import Path
from string import Template

from app.benchmark import VERDICTS, read_bounded
from app.core import catalog_hash

CASE_ID = re.compile(r"c_[0-9a-f]{16}")
SCORE_FILES = ("strict-score.json", "raw-score.json", "score.json")
STREAM_TITLES = (
    "\u539f\u59cb\u54cd\u5e94\u4e25\u683c\u89e3\u6790",
    "\u6240\u9009\u89e3\u6790\u6a21\u5f0f\u540e\u7684\u6a21\u578b\u5224\u51b3",
    "\u7b56\u7565\u540e\u7684\u5de5\u4f5c\u6d41\u7ed3\u679c",
)
LABELS = {
    "supported": "\u652f\u6301", "partially_supported": "\u90e8\u5206\u652f\u6301", "contradicted": "\u77db\u76fe",
    "insufficient_context": "\u4e0a\u4e0b\u6587\u4e0d\u8db3", "irrelevant": "\u4e0d\u76f8\u5173", "abstain": "\u5f03\u7b54",
    "decided": "\u6709\u6548\u5224\u51b3", "invalid": "\u7ed3\u679c\u65e0\u6548", "missing": "\u7f3a\u5931",
    "not_provided": "\u672a\u63d0\u4f9b\uff08\u65e0\u8bc4\u5206\u6587\u4ef6\uff09",
}
METRICS = {
    "total": "\u5168\u90e8\u6848\u4f8b", "submitted": "\u5df2\u63d0\u4ea4\u9884\u6d4b", "missing": "\u7f3a\u5931",
    "abstain": "\u5f03\u7b54", "invalid": "\u65e0\u6548", "valid_decisions": "\u6709\u6548\u5224\u51b3",
    "correct_valid_decisions": "\u4e0e\u6682\u5b9a\u6807\u7b7e\u4e00\u81f4", "false_support_count": "\u9519\u8bef\u652f\u6301",
    "invalid_support_attempts": "\u65e0\u6548\u652f\u6301\u5c1d\u8bd5",
}


def escape(value):
    if value is None:
        value = "\u672a\u63d0\u4f9b"
    return html.escape(str(value), quote=True)


def rows_by_id(rows, allowed):
    if not isinstance(rows, list):
        raise ValueError("invalid_rows")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid_row")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id not in allowed or case_id in result:
            raise ValueError("unknown_or_duplicate_case")
        result[case_id] = row
    return result


def load_run(run_dir):
    """Read only fixed JSON names and known case review files inside one directory."""
    root = Path(run_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("run_directory_required")

    def read(name, required=False):
        path = root / name
        if not path.exists():
            if required:
                raise ValueError("required_artifact_missing")
            return None
        if path.resolve().parent != root or not path.is_file():
            raise ValueError("artifact_outside_run")
        value = read_bounded(path)
        if not isinstance(value, dict):
            raise ValueError("artifact_object_required")
        return value

    pack = read("cases.json", True)
    execution = read("execution.json", True)
    if pack.get("schema") != "semantic-cases-v1" or execution.get("schema") != "local-model-execution-v1":
        raise ValueError("invalid_schema")
    if pack.get("clinical_release") is not False or execution.get("clinical_release") is not False:
        raise ValueError("development_artifacts_required")
    benchmark = pack.get("benchmark_sha256")
    if benchmark != catalog_hash({key: value for key, value in pack.items() if key != "benchmark_sha256"}):
        raise ValueError("changed_cases")
    cases = pack.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 500:
        raise ValueError("invalid_cases")
    case_ids = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("invalid_case")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or CASE_ID.fullmatch(case_id) is None or case_id in case_ids:
            raise ValueError("invalid_case_id")
        if case.get("case_sha256") != catalog_hash({key: value for key, value in case.items() if key != "case_sha256"}):
            raise ValueError("changed_case")
        if case.get("origin") not in ("synthetic", "public_excerpt") or not isinstance(case.get("claim"), str):
            raise ValueError("invalid_case_content")
        if not isinstance(case.get("evidence"), list) or not case["evidence"]:
            raise ValueError("missing_evidence")
        for evidence in case["evidence"]:
            if not isinstance(evidence, dict) or not isinstance(evidence.get("evidence_id"), str) or not isinstance(evidence.get("text"), str):
                raise ValueError("invalid_evidence")
        case_ids.add(case_id)
    if execution.get("benchmark_sha256") != benchmark:
        raise ValueError("execution_snapshot_mismatch")
    records = rows_by_id(execution.get("records"), case_ids)
    scores = {}
    score_rows = {}
    for name in SCORE_FILES:
        report = read(name)
        if report is not None and (report.get("schema") != "provisional-semantic-report-v1" or report.get("benchmark_sha256") != benchmark):
            raise ValueError("score_snapshot_mismatch")
        if report is not None and (report.get("clinical_release") is not False or not isinstance(report.get("overall"), dict)):
            raise ValueError("invalid_score_summary")
        scores[name] = report
        score_rows[name] = rows_by_id(report.get("cases"), case_ids) if report else {}
        for row in score_rows[name].values():
            if row.get("state") not in ("decided", "abstain", "invalid", "missing") or row.get("verdict") not in (*VERDICTS, "abstain", None):
                raise ValueError("invalid_score_outcome")
    reviews = {}
    for case in cases:
        case_id = case["case_id"]
        trace = read(case_id + ".review.json")
        embedded = trace.get("alignment") if trace else None
        alignment = read(case_id + ".alignment.json")
        if alignment is not None and embedded is not None and alignment != embedded:
            raise ValueError("alignment_artifacts_disagree")
        alignment = alignment if alignment is not None else embedded
        if alignment is not None:
            if (not isinstance(alignment, dict) or alignment.get("schema") != "local-response-alignment-v1" or
                    alignment.get("case_id") != case_id or alignment.get("case_sha256") != case["case_sha256"] or
                    alignment.get("clinical_release") is not False or
                    alignment.get("mode") not in ("none", "punctuation") or
                    alignment.get("state") not in ("not_run", "disabled", "unchanged", "aligned", "rejected", "interrupted") or
                    alignment.get("strict_state") not in ("not_run", "output_invalid", "decided", "invalid", "abstain") or
                    not isinstance(alignment.get("corrections"), list) or len(alignment["corrections"]) > 9):
                raise ValueError("invalid_alignment_artifact")
        if trace is not None or alignment is not None:
            trace = dict(trace or {})
            trace["_alignment_artifact"] = alignment
        reviews[case_id] = trace
    return pack, execution, records, scores, score_rows, reviews


def outcome(title, row, report_available=True):
    state = (row.get("state", "missing") if row else "missing") if report_available else "not_provided"
    verdict = row.get("verdict") if row else None
    severity = "danger" if state in ("invalid", "missing") else "neutral"
    label = LABELS.get(state, state)
    return (
        '<section class="outcome ' + severity + '"><h4>' + escape(title) + "</h4>"
        '<p class="state">' + escape(label) + " <code>" + escape(state) + "</code></p>"
        "<p>\u6a21\u578b\u6807\u7b7e\uff1a<strong>" + escape(LABELS.get(verdict, verdict)) + "</strong> <code>" + escape(verdict) + "</code></p>"
        "<p>\u951a\u70b9\u68c0\u67e5\uff1a" + escape(row.get("anchor_error") if row else None) + "</p></section>"
    )


def alignment_html(alignment, claim):
    """Display stored corrections as escaped text, with local range checks."""
    if alignment is None:
        return '<p class="meta">\u5bf9\u9f50\u8bb0\u5f55\uff1a\u672a\u63d0\u4f9b\uff1b\u4e0d\u63a8\u65ad\u65e7\u7248\u672c\u662f\u5426\u6267\u884c\u5bf9\u9f50\u3002</p>'
    chunks = [
        '<section class="alignment"><h3>\u539f\u6587\u6807\u70b9\u5bf9\u9f50</h3>',
        '<p>\u6a21\u5f0f\uff1a<code>' + escape(alignment.get("mode")) + '</code>\uff1b\u72b6\u6001\uff1a<code>' +
        escape(alignment.get("state")) + '</code>\uff1b\u4e25\u683c\u89e3\u6790\u72b6\u6001\uff1a<code>' +
        escape(alignment.get("strict_state")) + "</code></p>",
        '<p>\u539f\u56e0\uff1a<code>' + escape(alignment.get("reason")) +
        '</code>\uff1b\u683c\u5f0f\u6062\u590d\uff1a' + escape(alignment.get("format_recovered")) + "</p>",
        '<p>\u5bf9\u9f50\u6b65\u9aa4\u9644\u52a0\u6a21\u578b\u8c03\u7528\u6570\uff1a<code>' +
        escape(alignment.get("additional_model_calls")) + "</code></p>",
        '<p class="meta">\u5bf9\u9f50\u89c4\u5219\u4ec5\u5141\u8bb8\u8865\u56de\u539f\u6587\u4e2d\u7684\u4e2d\u6587\u9017\u53f7\u3001\u53e5\u53f7\u3001\u5206\u53f7\u548c\u7a7a\u767d\u3002\u6a21\u578b\u6807\u7b7e\u3001\u5f15\u53e5\u548c\u8bc1\u636e\u72b6\u6001\u4fdd\u7559\uff1b\u683c\u5f0f\u6062\u590d\u4e0d\u7b49\u4e8e\u8bed\u4e49\u5224\u65ad\u6b63\u786e\u3002</p>',
        '<p class="meta">\u539f\u59cb\u54cd\u5e94 SHA-256\uff1a<code>' + escape(alignment.get("response_sha256")) + "</code></p>",
    ]
    corrections = alignment["corrections"]
    if not corrections:
        chunks.append('<p class="meta">\u65e0\u8865\u56de\u5b57\u7b26\u8bb0\u5f55</p>')
    for correction in corrections:
        if not isinstance(correction, dict):
            raise ValueError("invalid_alignment_correction")
        start, end, text = correction.get("start"), correction.get("end"), correction.get("text")
        valid = (type(start) is int and type(end) is int and isinstance(text, str) and
                 0 <= start < end <= len(claim) and claim[start:end] == text and
                 all(char.isspace() or char in "\uff0c\u3002\uff1b" for char in text))
        chunks.append('<div class="correction"><p>\u539f\u6587\u4f4d\u7f6e [' + escape(start) + ", " +
                      escape(end) + ") \u00b7 " + escape(correction.get("placement")) +
                      "</p><pre>" + escape(text) + "</pre>")
        if not valid:
            chunks.append('<p class="danger">\u8865\u56de\u8bb0\u5f55\u672a\u901a\u8fc7\u539f\u6587\u8303\u56f4\u548c\u5141\u8bb8\u5b57\u7b26\u68c0\u67e5\u3002</p>')
        chunks.append("</div>")
    chunks.append("</section>")
    return "".join(chunks)


def quote_html(anchor, evidence):
    if not isinstance(anchor, dict):
        return '<p class="danger">\u65e0\u6548\u951a\u70b9\uff1a\u7ed3\u6784\u5f02\u5e38</p>'
    eid, start, end = anchor.get("evidence_id"), anchor.get("start"), anchor.get("end")
    text = evidence.get(eid) if isinstance(eid, str) else None
    valid = (isinstance(text, str) and type(start) is int and type(end) is int
             and 0 <= start < end <= len(text) and bool(text[start:end].strip()))
    location = escape(eid) + " [" + escape(start) + ", " + escape(end) + ")"
    if not valid:
        return '<p class="danger">\u65e0\u6548\u951a\u70b9\uff1a' + location + "</p>"
    return "<blockquote><div class=\"meta\">" + location + "</div>" + escape(text[start:end]) + "</blockquote>"


def render_case(case, record, result_rows, trace, index, available_scores):
    evidence = {item["evidence_id"]: item["text"] for item in case["evidence"]}
    origin = "\u5408\u6210\u6750\u6599\uff1a\u865a\u6784\u6848\u4f8b\uff0c\u4e0d\u662f\u771f\u5b9e\u7814\u7a76" if case["origin"] == "synthetic" else "\u516c\u5f00\u6458\u5f55\uff1a\u652f\u6301\u8303\u56f4\u4ec5\u9650\u7ed9\u5b9a\u6587\u672c"
    chunks = [
        '<article class="case"><header class="case-header"><h2>' + str(index) + ". " + escape(case["case_id"]) + "</h2>",
        '<p class="origin">' + escape(origin) + "</p></header>",
        "<h3>\u539f\u59cb\u65ad\u8a00</h3><p class=\"claim\">" + escape(case["claim"]) + "</p>",
        '<div class="outcomes">' + "".join(outcome(title, result_rows[name], name in available_scores)
            for name, title in zip(SCORE_FILES, STREAM_TITLES)) + "</div>",
        '<p class="meta">\u6682\u5b9a\u53c2\u8003\u6807\u7b7e\uff1a' +
        escape(next((row.get("expected") for row in result_rows.values() if row), None)) + "</p>",
        "<p>\u6267\u884c\u72b6\u6001\uff1a<code>" + escape(record.get("state", "not_attempted") if record else "not_attempted") + "</code>"
        "\uff1b\u5931\u8d25\u8bb0\u5f55\uff1a<code>" + escape(record.get("error") if record else None) + "</code>"
        "\uff1b\u8017\u65f6\uff08\u79d2\uff09\uff1a" + escape(record.get("elapsed_seconds") if record else None) + "</p>",
    ]
    reasons = (trace or record or {}).get("policy_reasons", [])
    chunks.append("<p>\u7b56\u7565\u539f\u56e0\uff1a<code>" + escape(json.dumps(reasons, ensure_ascii=False)) + "</code></p>")
    chunks.append(alignment_html((trace or {}).get("_alignment_artifact"), case["claim"]))
    if trace and "parts" in trace:
        if trace.get("contract") == "span_ids_v1":
            chunks.append('<p class="meta">ID contract: <code>' + escape(trace["contract"]) +
                          '</code>; unitization: <code>' + escape(trace.get("unitization")) +
                          '</code>. ID coverage is not semantic decomposition.</p>')
        chunks.append('<p class="meta">\u6a21\u578b\u8bc1\u636e\u72b6\u6001\uff1a' + escape(trace.get("evidence_status")) +
                      "\uff1b\u6587\u672c\u8986\u76d6\u68c0\u67e5\uff1a" + escape(trace.get("text_coverage_verified")) +
                      "\uff1b\u8bed\u4e49\u539f\u5b50\u6027\uff1a" + escape(trace.get("semantic_atomicity")) + "</p>")
        chunks.append('<p class="meta">\u6240\u9009\u89e3\u6790\u6a21\u5f0f\u540e\u7684\u6a21\u578b\u72b6\u6001 / \u6807\u7b7e\uff1a' + escape(trace.get("raw_state")) + " / " +
                      escape(trace.get("raw_verdict")) + "\uff1b\u5de5\u4f5c\u6d41\u72b6\u6001 / \u6807\u7b7e\uff1a" +
                      escape(trace.get("workflow_state")) + " / " + escape(trace.get("workflow_verdict")) + "</p>")
        parts = trace.get("parts", [])
        if not isinstance(parts, list):
            raise ValueError("invalid_review_parts")
        chunks.append("<h3>\u9010\u9879\u5224\u8bfb</h3>")
        for number, part in enumerate(parts, 1):
            if not isinstance(part, dict) or not isinstance(part.get("anchors", []), list):
                raise ValueError("invalid_review_part")
            chunks.append('<section class="part"><h4>\u5224\u8bfb\u7247\u6bb5 ' + str(number) + " [" + escape(part.get("start")) +
                          ", " + escape(part.get("end")) + ")</h4><p>" + escape(part.get("text")) +
                          "</p><p>\u6a21\u578b\u6807\u7b7e\uff1a<code>" + escape(part.get("verdict")) +
                          "</code>\uff1b\u951a\u70b9\u68c0\u67e5\uff1a<code>" + escape(part.get("anchor_error")) + "</code></p>")
            if "unit_ids" in part:
                chunks.append('<p class="meta">unit_ids: <code>' +
                              escape(json.dumps(part["unit_ids"], ensure_ascii=False)) + '</code></p>')
            if part.get("anchor_error"):
                chunks.append('<p class="danger">\u951a\u70b9\u65e0\u6548\uff1b\u8be5\u6807\u7b7e\u4e0d\u80fd\u89c6\u4e3a\u6709\u6548\u652f\u6301\u3002</p>')
            anchors = part.get("anchors", [])
            chunks.extend(quote_html(anchor, evidence) for anchor in anchors)
            if not anchors:
                chunks.append('<p class="meta">\u65e0\u5f15\u53e5\u951a\u70b9</p>')
            chunks.append("</section>")
    else:
        chunks.append('<p class="meta">\u65e0\u9010\u9879\u8bb0\u5f55\uff1b\u53ef\u80fd\u4e3a\u57fa\u7ebf\u7b56\u7565\u3001\u672a\u6267\u884c\u6216\u6267\u884c\u5931\u8d25\u3002\u6b64\u9875\u4e0d\u8865\u9020\u62c6\u5206\u6216\u5f15\u53e5\u3002</p>')
    chunks.append("<details open><summary>\u539f\u59cb\u8bc1\u636e\u4e0e\u6765\u6e90\u4fe1\u606f</summary>")
    for item in case["evidence"]:
        chunks.append("<section><h4>" + escape(item["evidence_id"]) + "</h4><blockquote>" + escape(item["text"]) +
                      "</blockquote><p class=\"meta\">\u5b9a\u4f4d\uff1a" + escape(item.get("locator")) + "</p>")
        source = item.get("source")
        if isinstance(source, dict):
            chunks.append('<dl class="source">')
            for key in ("title", "pmid", "doi", "url", "verification_scope", "currency"):
                chunks.append("<dt>" + escape(key) + "</dt><dd>" + escape(source.get(key)) + "</dd>")
            chunks.append("</dl>")
        chunks.append("</section>")
    chunks.append("</details></article>")
    return "".join(chunks)


def summary_table(scores):
    rows = []
    for key, label in METRICS.items():
        values = [(scores[name] or {}).get("overall", {}).get(key) for name in SCORE_FILES]
        rows.append("<tr><th scope=\"row\">" + escape(label) + "</th>" +
                    "".join("<td>" + escape(value) + "</td>" for value in values) + "</tr>")
    return "".join(rows)


def generate_report(run_dir, output):
    """Render escaped text only and preserve all existing output files."""
    output = Path(output)
    if output.suffix.lower() != ".html":
        raise ValueError("html_output_required")
    if output.exists():
        raise FileExistsError()
    pack, execution, records, scores, score_rows, reviews = load_run(run_dir)
    available_scores = {name for name in SCORE_FILES if scores[name] is not None}
    cards = "".join(render_case(case, records.get(case["case_id"]),
                              {name: score_rows[name].get(case["case_id"]) for name in SCORE_FILES},
                              reviews[case["case_id"]], index, available_scores)
                    for index, case in enumerate(pack["cases"], 1))
    template = Template(Path(__file__).with_name("report_template.html").read_text(encoding="utf-8"))
    document = template.substitute(
        model=escape(execution.get("model")), strategy=escape(execution.get("strategy")),
        status=escape(execution.get("status")), settings=escape(json.dumps(execution.get("settings"), ensure_ascii=False)),
        counts=escape(json.dumps(execution.get("counts"), ensure_ascii=False)),
        score_availability="; ".join(escape(name) + ": " + escape(
            "\u5df2\u63d0\u4f9b" if name in available_scores else "\u672a\u63d0\u4f9b") for name in SCORE_FILES),
        benchmark=escape(pack["benchmark_sha256"]), metrics=summary_table(scores), cases=cards,
    )
    with output.open("x", encoding="utf-8") as stream:
        stream.write(document)
    return {"cases": len(pack["cases"]), "clinical_release": False, "output": str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = generate_report(args.run_dir, args.output)
    except (ValueError, TypeError, KeyError, OSError, RecursionError):
        parser.exit(2, "Report not created. Check fixed JSON artifacts, fingerprints and a new HTML output path.\n")
    print("Created offline review for " + str(result["cases"]) + " cases; no clinical approval.")


if __name__ == "__main__":
    main()
