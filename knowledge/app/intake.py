"""Stage explicitly public reference drafts without modifying the live corpus."""

import argparse
import hashlib
import json
from pathlib import Path

from app.core import parse_json, validate_catalog
from app.review import review_packet

MAX_FILE = 2 * 1024 * 1024


def stage(input_path, output_path, public_reference_only=False):
    """Validate structure only; an operator declaration cannot detect PHI."""
    if not public_reference_only:
        raise ValueError("public_reference_declaration_required")
    with Path(input_path).open("rb") as source:
        raw = source.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError("input_too_large")
    catalog = validate_catalog(parse_json(raw.decode("utf-8-sig")))
    if not catalog["sources"] or not catalog["claims"]:
        raise ValueError("empty_draft")
    for source in catalog["sources"]:
        if source["origin"] != "public" or source["currency"] != "unknown":
            raise ValueError("public_unconfirmed_sources_only")
    for claim in catalog["claims"]:
        if claim["review"] != "pending" or any(claim.get(k) is not None for k in ("reviewer", "reviewed_at", "reviewed_binding_sha256")):
            raise ValueError("pending_drafts_only")
    packet = {
        "schema": "staged-public-draft-v1", "live_corpus_modified": False,
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "validation": {"structure": "PASS", "source_identity": "NOT_INDEPENDENTLY_VERIFIED", "semantic_support": "NOT_RUN", "privacy": "OPERATOR_DECLARATION_ONLY"},
        "catalog": catalog, "review_packet": review_packet(catalog),
    }
    # Exclusive creation protects both the input and previously staged work.
    with Path(output_path).open("x", encoding="utf-8") as target:
        json.dump(packet, target, ensure_ascii=True, indent=2)
        target.write("\n")
    return packet


def main():
    parser = argparse.ArgumentParser(description="Validate and stage PUBLIC reference drafts locally; never supply patient data")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--public-reference-only", action="store_true", help="Declare input is public reference material without patient information")
    args = parser.parse_args()
    try:
        packet = stage(args.input, args.output, args.public_reference_only)
    except (ValueError, TypeError, OSError, RecursionError):
        parser.exit(2, "Draft not staged. Check schema, public/pending state, size and an unused writable output path.\n")
    print(f"Staged {len(packet['catalog']['claims'])} pending claims. Live corpus unchanged; independent source and clinical review not performed.")


if __name__ == "__main__":
    main()
