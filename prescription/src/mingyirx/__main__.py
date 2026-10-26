from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import ConfigError
from .dashboard import DashboardError, build_dashboard
from .dashboard_sources import build_source_dashboard
from .io import InputError
from .pipeline import run_pipeline, validate_pipeline
from .terminology import TerminologyError, compile_dictionary, prepare_dictionary
from .inheritance import (
    InheritanceError, assert_output_allowed, build_view, freeze_bundle,
    load_bundle, read_frozen, template_bundle, validate_bundle, verify_frozen,
)
from .dashboard_inheritance import render_inheritance


def build_inheritance(input_dir: Path, output: Path) -> dict:
    """Render the same verified snapshot; never reopen a case file after review."""
    bundle = read_frozen(input_dir)
    assert_output_allowed(bundle, output)
    page = render_inheritance(bundle, build_view(bundle))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(page)
    return {"gate": "PASS_WITH_WARNINGS", "synthetic": bundle["synthetic"],
            "content_sha256": validate_bundle(bundle)["content_sha256"],
            "clinical_validation": False}


def _privacy_threshold(value: str) -> int:
    parsed = int(value)
    if parsed < 10:
        raise argparse.ArgumentTypeError("Presentation threshold must be at least 10")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mingyirx",
        description="Privacy-first longitudinal prescription analytics",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate input and cohort construction")
    validate.add_argument("--config", type=Path, required=True)
    validate.add_argument(
        "--input", type=Path, action="append", required=True, help="Repeat for each source CSV"
    )

    run = subparsers.add_parser("run", help="Validate and generate aggregate outputs")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument(
        "--input", type=Path, action="append", required=True, help="Repeat for each source CSV"
    )
    run.add_argument("--output", type=Path, required=True)

    dashboard = subparsers.add_parser(
        "dashboard", help="Build a self-contained dashboard from public aggregate outputs"
    )
    dashboard.add_argument("--input-dir", type=Path, required=True)
    dashboard.add_argument("--output", type=Path, required=True)
    dashboard.add_argument("--title", default="MingYiRx 处方记录复盘")
    sources = subparsers.add_parser("dashboard-sources", help="Switch two reviewed dashboards without merging patients")
    sources.add_argument("--primary", type=Path, required=True)
    sources.add_argument("--supplement", type=Path, required=True)
    sources.add_argument("--output", type=Path, required=True)
    for command in (dashboard, sources):
        command.add_argument("--privacy-policy", choices=("conservative-v1", "synthetic-showcase-v1"), default=None,
                             help="Apply a presentation projection; showcase requires explicitly synthetic input")
        command.add_argument("--min-public-n", type=_privacy_threshold, default=10,
                             help="Minimum presentation count; cannot lower a recorded source threshold")
    prepare = subparsers.add_parser("dictionary-prepare", help="Prepare a public vocabulary review ledger")
    prepare.add_argument("--input-dir", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    compile_review = subparsers.add_parser("dictionary-compile", help="Compile explicitly approved terminology")
    compile_review.add_argument("--review", type=Path, required=True)
    compile_review.add_argument("--version", required=True)
    compile_review.add_argument("--output", type=Path, required=True)
    inheritance_template = subparsers.add_parser("inheritance-template", help="Write a blank coded case import template")
    inheritance_template.add_argument("--output", type=Path, required=True)
    inheritance_validate = subparsers.add_parser("inheritance-validate", help="Validate a local coded case bundle")
    inheritance_validate.add_argument("--input", type=Path, required=True)
    inheritance_freeze = subparsers.add_parser("inheritance-freeze", help="Freeze a validated bundle into a new directory")
    inheritance_freeze.add_argument("--input", type=Path, required=True)
    inheritance_freeze.add_argument("--output", type=Path, required=True)
    inheritance_verify = subparsers.add_parser("inheritance-verify", help="Verify frozen package bytes and membership")
    inheritance_verify.add_argument("--input-dir", type=Path, required=True)
    inheritance_build = subparsers.add_parser("inheritance-build", help="Render a verified local case workspace")
    inheritance_build.add_argument("--input-dir", type=Path, required=True)
    inheritance_build.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "validate":
            context = validate_pipeline(args.config, args.input)
            summary = {
                "gate": context.gate,
                "source_files": len(context.read_result.source_files),
                "source_rows": context.read_result.row_count,
                "analysis_rows": context.read_result.analysis_row_count,
                "cross_file_overlap_rows_removed": (
                    context.read_result.cross_file_overlap_rows_removed
                ),
                "source_patients": context.cohort_result.total_patients,
                "assigned_patients": len(context.cohort_result.patient_groups),
                "group_counts": context.cohort_result.group_counts,
                "warnings": list(context.warnings),
            }
        elif args.command == "run":
            summary = run_pipeline(args.config, args.input, args.output)
        elif args.command == "dictionary-prepare":
            summary = prepare_dictionary(args.input_dir, args.output)
        elif args.command == "dictionary-compile":
            summary = compile_dictionary(args.review, args.version, args.output)
        elif args.command == "dashboard-sources":
            summary = build_source_dashboard(args.primary, args.supplement, args.output,
                                             privacy_policy=args.privacy_policy, min_public_n=args.min_public_n)
        elif args.command == "inheritance-template":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(template_bundle(), handle, ensure_ascii=True, indent=2)
                handle.write("\n")
            summary = {"gate": "TEMPLATE_ONLY", "freezeable": False}
        elif args.command == "inheritance-validate":
            summary = validate_bundle(load_bundle(args.input))
        elif args.command == "inheritance-freeze":
            summary = freeze_bundle(args.input, args.output)
        elif args.command == "inheritance-verify":
            summary = verify_frozen(args.input_dir)
        elif args.command == "inheritance-build":
            summary = build_inheritance(args.input_dir, args.output)
        else:
            summary = build_dashboard(args.input_dir, args.output, args.title,
                                      privacy_policy=args.privacy_policy, min_public_n=args.min_public_n)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2 if summary.get("gate") == "BLOCK" else 0
    except (ConfigError, DashboardError, InputError, TerminologyError, InheritanceError, json.JSONDecodeError) as error:
        print(json.dumps({"gate": "BLOCK", "error": str(error)}, ensure_ascii=False, indent=2))
        return 2
    except (OSError, UnicodeError):
        print(json.dumps({"gate": "BLOCK", "error": "File access or text decoding failed; input details withheld"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
