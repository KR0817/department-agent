"""Exercise the installed command boundary with synthetic fixtures only."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mingyirx.__main__ import main
from mingyirx.dashboard import DashboardError
from mingyirx.inheritance import freeze_bundle, load_bundle
from mingyirx.reviewed_dashboard import build_reviewed_dashboard
from test_reviewed_dashboard import fixture

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/synthetic/inheritance_cases.json"


def invoke(*arguments):
    output = io.StringIO()
    with patch("sys.argv", ["mingyirx", *map(str, arguments)]), contextlib.redirect_stdout(output):
        code = main()
    return code, json.loads(output.getvalue())


class InheritanceCliTests(unittest.TestCase):
    def test_template_is_not_a_case_package_and_is_new_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "template.json"
            code, report = invoke("inheritance-template", "--output", path)
            self.assertEqual(code, 0)
            self.assertFalse(report["freezeable"])
            before = path.read_bytes()
            self.assertEqual(invoke("inheritance-template", "--output", path)[0], 2)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(invoke("inheritance-validate", "--input", path)[0], 2)
            self.assertEqual(invoke("inheritance-freeze", "--input", path, "--output", Path(temporary) / "frozen")[0], 2)

    def test_full_freeze_verify_build_sequence_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen, page = root / "frozen", root / "page.html"
            self.assertEqual(invoke("inheritance-validate", "--input", INPUT)[0], 0)
            self.assertEqual(invoke("inheritance-freeze", "--input", INPUT, "--output", frozen)[0], 0)
            self.assertEqual(invoke("inheritance-verify", "--input-dir", frozen)[0], 0)
            self.assertEqual(invoke("inheritance-build", "--input-dir", frozen, "--output", page)[0], 0)
            original = page.read_bytes()
            self.assertEqual(invoke("inheritance-build", "--input-dir", frozen, "--output", page)[0], 2)
            self.assertEqual(page.read_bytes(), original)
            (frozen / "bundle.json").write_text("{}", encoding="utf-8")
            self.assertEqual(invoke("inheritance-verify", "--input-dir", frozen)[0], 2)
            destination = root / "tampered.html"
            self.assertEqual(invoke("inheritance-build", "--input-dir", frozen, "--output", destination)[0], 2)
            self.assertFalse(destination.exists())

    def test_invalid_input_returns_nonzero_without_submitted_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.json"
            payload = load_bundle(INPUT)
            payload["untrusted_field"] = "SECRET-LIKE-UNTRUSTED-VALUE"
            path.write_text(json.dumps(payload), encoding="utf-8")
            code, report = invoke("inheritance-validate", "--input", path)
            self.assertEqual(code, 2)
            self.assertNotIn("SECRET-LIKE-UNTRUSTED-VALUE", json.dumps(report))

    def test_optional_workspace_preserves_aggregate_payload_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = root / "reviewed"
            release.mkdir()
            _, contract = fixture(release)
            frozen = root / "frozen"
            freeze_bundle(INPUT, frozen)
            first = build_reviewed_dashboard(release, root / "a", contract, inheritance_frozen=frozen)
            second = build_reviewed_dashboard(release, root / "b", contract, inheritance_frozen=frozen)
            self.assertEqual(first, second)
            self.assertEqual(first["payloads_preserved"], {"primary": True, "supplement": True})
            self.assertTrue(first["inheritance_workspace"]["synthetic"])
            self.assertIn("inheritance.html", first["files"])
            self.assertIn("inheritance-template.json", first["files"])
            page = (root / "a/local/index.html").read_text(encoding="utf-8")
            self.assertTrue('href="inheritance.html"' in page)
            self.assertFalse("SYNTHETIC-INHERITANCE" in page)

    def test_original_delivery_rejects_nonsynthetic_cases_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = root / "reviewed"
            release.mkdir()
            _, contract = fixture(release)
            clinical = deepcopy(load_bundle(INPUT))
            clinical.update(synthetic=False, deidentified=True, local_authorization=True)
            with patch("mingyirx.inheritance.read_frozen", return_value=clinical):
                with self.assertRaises(DashboardError):
                    build_reviewed_dashboard(release, root / "build", contract, inheritance_frozen=root / "placeholder")
            self.assertFalse((root / "build").exists())


if __name__ == "__main__":
    unittest.main()
