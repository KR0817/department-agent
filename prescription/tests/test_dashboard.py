from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from mingyirx.dashboard import DashboardError, HTML_TEMPLATE, _read_rows
from mingyirx.dashboard_research import public_provenance


class DashboardInputTests(unittest.TestCase):
    def test_public_provenance_is_allowlisted_and_checks_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "aggregate.csv"
            source.write_text("group,patients\nra,10\n", encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = {"project_id": "synthetic-project", "dataset_id": "synthetic-v1",
                        "cohort_version": "v1", "mingyirx_version": "0.14.0", "gate": "PASS_WITH_WARNINGS",
                        "configuration": {"min_public_n": 10, "synthetic_mode": False,
                                          "absolute_path": "PRIVATE_SENTINEL", "sha256": "a" * 64},
                        "inputs": [{"absolute_path": "PRIVATE_SENTINEL"}],
                        "warnings": ["PRIVATE_SENTINEL"], "cohort_flow": {"excluded": 1},
                        "artifacts": {source.name: digest}}
            (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            public = public_provenance(root, [source.name])
            self.assertEqual(public["artifact_check"], "PASS")
            self.assertEqual(public["analysis_version"], "0.14.0")
            self.assertEqual(public["min_public_n"], 10)
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(public))
            self.assertNotIn("cohort_flow", public)
            source.write_text("group,patients\nra,11\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                public_provenance(root, [source.name])

    def test_missing_partial_and_invalid_manifest_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["one.csv", "two.csv"]:
                (root / name).write_text("group,patients\nra,10\n", encoding="utf-8")
            names = ["one.csv", "two.csv"]
            public = public_provenance(root, names)
            self.assertEqual(public["artifact_check"], "NOT_ASSESSED")
            self.assertIsNone(public["dataset_id"])
            path = root / "run_manifest.json"
            path.write_text(json.dumps({"artifacts": {"one.csv": public["source_sha256"]["one.csv"]}}), encoding="utf-8")
            self.assertEqual(public_provenance(root, names)["artifact_check"], "PARTIAL")
            for source in ['[1]', '{bad', '{"configuration": []}', '{"gate": "BLOCK"}',
                           '{"configuration": {"min_public_n": 2, "synthetic_mode": false}}']:
                with self.subTest(source=source):
                    path.write_text(source, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        public_provenance(root, names)

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable for JavaScript execution")
    def test_generated_dashboard_interactions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dashboard.html"
            path.write_text(HTML_TEMPLATE, encoding="utf-8")
            result = subprocess.run(
                ["node", str(Path(__file__).with_name("dashboard_ui_checks.mjs")), str(path), directory],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in ["annual.svg", "network.svg"]:
                svg = ET.parse(Path(directory) / name).getroot()
                self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")
                meta = json.loads(svg.find("{http://www.w3.org/2000/svg}metadata").text)
                self.assertEqual(meta["provenance"]["dataset_id"], "synthetic-v1")
                self.assertGreater(float(svg.attrib["height"]), 286)
                self.assertIsNotNone(svg.find("{http://www.w3.org/2000/svg}style"))

    def test_only_declared_fields_are_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aggregate.csv"
            path.write_text("group,patients,private_note\nra,10,SYNTHETIC_SENTINEL\n", encoding="utf-8")
            self.assertEqual(_read_rows(path, {"group", "patients"}), [{"group": "ra", "patients": "10"}])

    def test_sensitive_headers_and_malformed_rows_are_rejected_without_values(self):
        examples = [
            "group,patients, Patient_ID \nra,10,SYNTHETIC_SENTINEL\n",
            "group,patients,group\nra,10,SYNTHETIC_SENTINEL\n",
            "group,patients\nra,10,SYNTHETIC_SENTINEL\n",
            "group,patients\nSYNTHETIC_SENTINEL\n",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aggregate.csv"
            for source in examples:
                with self.subTest(source=source.splitlines()[0]):
                    path.write_text(source, encoding="utf-8")
                    with self.assertRaises(DashboardError) as caught:
                        _read_rows(path, {"group", "patients"})
                    self.assertNotIn("SYNTHETIC_SENTINEL", str(caught.exception))

    def test_quoted_fields_and_blank_suppressed_values_remain_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aggregate.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["group", "patients"])
                writer.writerow(['synthetic, "group"', ""])
            self.assertEqual(_read_rows(path, {"group", "patients"}), [{"group": 'synthetic, "group"', "patients": ""}])
