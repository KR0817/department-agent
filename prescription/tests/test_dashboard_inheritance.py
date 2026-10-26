"""Synthetic page and actual native controller regression checks."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from mingyirx.dashboard_inheritance import CSS, JS, render_inheritance
from mingyirx.inheritance import InheritanceError, build_view, validate_bundle


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / "data/synthetic/inheritance_cases.json").read_text(encoding="utf-8"))


class InheritanceDashboardTests(unittest.TestCase):
    def test_render_is_identical_for_equivalent_recursive_key_orders(self):
        def reversed_keys(value):
            if isinstance(value, dict):
                return {key: reversed_keys(item) for key, item in reversed(list(value.items()))}
            if isinstance(value, list):
                return [reversed_keys(item) for item in value]
            return value

        bundle = fixture()
        reordered = reversed_keys(bundle)
        self.assertEqual(bundle, reordered)
        self.assertNotEqual(json.dumps(bundle), json.dumps(reordered))
        self.assertEqual(
            render_inheritance(bundle, build_view(bundle)),
            render_inheritance(reordered, build_view(reordered)),
        )

    def test_embedded_bundle_and_view_are_exact_and_source_is_not_mutated(self):
        bundle = fixture()
        original = deepcopy(bundle)
        view = build_view(bundle)
        page = render_inheritance(bundle, view)
        embedded = json.loads(re.search(r'<script id="inheritance-data" type="application/json">(.*?)</script>', page, re.S)[1])
        self.assertEqual(embedded, {"bundle": bundle, "view": view})
        self.assertEqual(bundle, original)
        for number in range(1, 6):
            self.assertEqual(page.count(f'id="stage-{number}"'), 1)
            self.assertEqual(page.count(f'id="step-{number}"'), 1)
        self.assertNotRegex(JS, r"\bfetch\s*\(|\bXMLHttpRequest\b|\blocalStorage\b|\bsessionStorage\b|\beval\s*\(|new Function\s*\(")
        self.assertNotRegex(CSS, r"@import|url\(")
        self.assertIn("connect-src 'none'", page)
        self.assertIn("max-width:800px", CSS)
        self.assertIn("max-width:480px", CSS)

    def test_invalid_bundle_and_altered_or_stale_view_fail_closed(self):
        bundle = fixture()
        view = build_view(bundle)
        invalid = deepcopy(bundle)
        invalid["unexpected"] = "private unsafe value"
        with self.assertRaisesRegex(InheritanceError, "INHERITANCE_RENDER_INVALID"):
            render_inheritance(invalid, view)
        stale = deepcopy(view)
        stale["validation"]["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(InheritanceError, "INHERITANCE_RENDER_STALE_VIEW"):
            render_inheritance(bundle, stale)
        altered = deepcopy(view)
        altered["pairs"][0]["added"] = ["MAIDONG"]
        with self.assertRaises(InheritanceError):
            render_inheritance(bundle, altered)

    def test_script_data_escaping_preserves_safe_quotes_and_ampersands(self):
        bundle = fixture()
        bundle["physicians"][0]["label"] = 'Synthetic "A" & B __JS__'
        page = render_inheritance(bundle, build_view(bundle))
        embedded = re.search(r'<script id="inheritance-data" type="application/json">(.*?)</script>', page, re.S)[1]
        self.assertIn(r"\u0026", embedded)
        self.assertNotIn("Synthetic &", embedded)
        self.assertEqual(json.loads(embedded)["bundle"]["physicians"][0]["label"], bundle["physicians"][0]["label"])
        bundle["physicians"][0]["label"] = "</script><script>bad()</script>"
        with self.assertRaises(InheritanceError):
            render_inheritance(bundle, {})

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_real_controller_and_export_roundtrip_through_core_validator(self):
        bundle = fixture()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            page = target / "inheritance.html"
            page.write_text(render_inheritance(bundle, build_view(bundle)), encoding="utf-8")
            result = subprocess.run(
                ["node", str(ROOT / "tests/inheritance_ui_checks.mjs"), str(page), str(target)],
                capture_output=True, text=True, encoding="utf-8", timeout=45,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in ("edited-bundle.json", "revised-existing-bundle.json"):
                revised = json.loads((target / name).read_text(encoding="utf-8"))
                validation = validate_bundle(revised)
                self.assertNotEqual(validation["gate"], "BLOCK", validation["errors"])
                self.assertEqual(revised["revision"], bundle["revision"] + 1)
                self.assertEqual(revised["parent_sha256"], build_view(bundle)["validation"]["content_sha256"])
                self.assertIn("inheritance-data", render_inheritance(revised, build_view(revised)))


if __name__ == "__main__":
    unittest.main()
