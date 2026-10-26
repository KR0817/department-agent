"""Generated fixtures exercise original-release gates without clinical files."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from mingyirx.dashboard import DashboardError
from mingyirx.reviewed_dashboard import (
    ARTIFACTS, TABLES, build_reviewed_dashboard, extract_payload,
    load_reviewed_release, payload_hash, sha256, validate_payload,
)


def fixture(root):
    public = root / "public"
    public.mkdir()
    payload = {key: [] for key in TABLES}
    payload.update({"version": "fixture", "clinicalMode": True, "research": {},
        "provenance": {"synthetic_mode": False, "min_public_n": 10,
                       "dataset_id": "fixture", "cohort_version": "fixture-v1"}})
    page = '<script id="dashboard-data" type="application/json">' + json.dumps(payload) + '</script>'
    page += '<script id="supplement-data" type="application/json">' + json.dumps(payload) + '</script>'
    for name in ARTIFACTS:
        (public / name).write_text(page if name == "index.html" else "Fixture only\n", encoding="utf-8")
    hashes = {name: sha256(public / name) for name in ARTIFACTS}
    (root / "manifest.json").write_text(json.dumps({"artifacts": hashes}), encoding="utf-8")
    contract = {"contract_version": "fixture-v1", "reviewed_release": "fixture", "artifacts": hashes, "payloads": {}}
    for source, element in (("primary", "dashboard-data"), ("supplement", "supplement-data")):
        contract["payloads"][source] = {"element_id": element, "sha256": payload_hash(payload),
            "dataset_id": "fixture", "cohort_version": "fixture-v1", "synthetic_mode": False, "groups": {}}
    return payload, contract


class ReviewedReleaseTests(unittest.TestCase):
    def test_loads_only_pinned_aggregate_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload, contract = fixture(root)
            (root / "unrelated-do-not-read.csv").write_bytes(b"not read")
            actual, hashes = load_reviewed_release(root, contract)
            self.assertEqual(actual, {"primary": payload, "supplement": payload})
            self.assertEqual(hashes, contract["artifacts"])

    def test_changed_file_or_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, contract = fixture(root)
            (root / "public/index.html").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(DashboardError, "hash mismatch"):
                load_reviewed_release(root, contract)
            (root / "manifest.json").write_text('{"artifacts": {}}', encoding="utf-8")
            with self.assertRaisesRegex(DashboardError, "pinned"):
                load_reviewed_release(root, contract)

    def test_path_expansion_and_wrong_payload_identity_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, contract = fixture(root)
            bad = deepcopy(contract)
            bad["artifacts"]["../arbitrary.csv"] = "0" * 64
            with self.assertRaisesRegex(DashboardError, "allowlist"):
                load_reviewed_release(root, bad)
            contract["payloads"]["primary"]["dataset_id"] = "other"
            with self.assertRaisesRegex(DashboardError, "identity mismatch"):
                load_reviewed_release(root, contract)

    def test_patient_fields_dates_paths_and_synthetic_flags_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            payload, _ = fixture(Path(temporary))
            for value in (True, "false", None, 0):
                changed = deepcopy(payload)
                changed["provenance"]["synthetic_mode"] = value
                with self.assertRaises(DashboardError):
                    validate_payload(changed)
            for row in ({"patient_id": "fixture"}, {"label": "2020-01-01"}, {"label": "C:/private/input.csv"}):
                changed = deepcopy(payload)
                changed["items"] = [row]
                with self.assertRaises(DashboardError):
                    validate_payload(changed)

    def test_duplicate_payload_blocks_are_rejected(self):
        block = '<script id="dashboard-data" type="application/json">{}</script>'
        with self.assertRaisesRegex(DashboardError, "exactly one"):
            extract_payload(block + block, "dashboard-data")

    def test_current_template_preserves_original_payload_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = root / "release"
            release.mkdir()
            payload, contract = fixture(release)
            first = build_reviewed_dashboard(release, root / "build-a", contract)
            second = build_reviewed_dashboard(release, root / "build-b", contract)
            self.assertEqual(first["files"], second["files"])
            self.assertEqual(first["zip_sha256"], second["zip_sha256"])
            self.assertTrue(all(first["payloads_preserved"].values()))
            page = (root / "build-a/local/index.html").read_text(encoding="utf-8")
            self.assertIn('id="original-context"', page)
            loaded = extract_payload(page, "dashboard-data")
            self.assertEqual(loaded["provenance"], payload["provenance"])
            self.assertTrue(loaded["presentation"]["local_aggregate_only"])
            with self.assertRaises(FileExistsError):
                build_reviewed_dashboard(release, root / "build-a", contract)


if __name__ == "__main__":
    unittest.main()
