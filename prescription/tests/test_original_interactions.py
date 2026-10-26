"""Synthetic boundary fixtures for reviewed-aggregate presentation interactions."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from mingyirx.dashboard import DashboardError, HTML_TEMPLATE
from mingyirx.dashboard_sources import build_source_dashboard


def fixture(supplement=False):
    """Fabricated rows simulate legacy real-source metadata without clinical inputs."""
    groups = [{"code": "ra", "label": "Rheumatoid arthritis", "patients": "40", "disease_count": "1"},
              {"code": "sjd", "label": "Sjogren disease", "patients": "30", "disease_count": "1"},
              {"code": "ra__sjd", "label": "Rheumatoid arthritis + Sjogren disease", "patients": "20", "disease_count": "2"},
              {"code": "ra__as", "label": "Rheumatoid arthritis + Ankylosing spondylitis", "patients": "10", "disease_count": "2"}]
    if supplement:
        groups = [{"code": "as", "label": "Ankylosing spondylitis", "patients": "20", "disease_count": "1"}]
    summaries, items, changes, comparisons = [], [], [], []
    for group in groups:
        base = {"group": group["code"], "stratum_type": "overall", "stratum": "all"}
        summaries.append({**base, "patients": group["patients"], "repeat_patients": group["patients"]})
        items.append({**base, "item_name": "Herb A", "prevalence": ".5", "exposed_patients": str(int(group["patients"])//2), "group_patients": group["patients"]})
        if group["code"] != "sjd":
            for direction in ["addition", "removal"]:
                changes.append({**base, "item_name": "Herb A", "change_type": direction, "patients_with_change": "10", "repeat_patients": group["patients"], "patient_prevalence": str(10/int(group["patients"])), "mean_patient_transition_fraction": ".2"})
    if not supplement:
        summaries.append({"group": "ra", "stratum_type": "sex", "stratum": "female", "stratum_label": "Female", "patients": "20"})
        for direction, difference in [("addition", ".1"), ("removal", "-.1")]:
            comparisons.append({"combination_group": "ra__sjd", "single_group": "ra", "combination_label": groups[2]["label"], "single_label": groups[0]["label"], "stratum_type": "overall", "stratum": "all", "item_name": "Herb A", "change_type": direction, "combination_prevalence": ".5", "single_prevalence": ".25", "combination_mean_transition_fraction": str(.2+float(difference)), "single_mean_transition_fraction": ".2", "mean_transition_fraction_difference": difference})
    return {"version": "historic-fixture", "clinicalMode": True, "groups": groups,
            "presentation": {"local_aggregate_only": True, "renderer_version": "test-renderer"},
            "provenance": {"dataset_id": "fabricated-test-only", "synthetic_mode": False},
            "summaries": summaries, "items": items, "changes": changes, "comparisons": comparisons,
            "yearSummaries": [{**row, "year": "2020"} for row in summaries],
            "yearItems": [{**row, "year": "2020"} for row in items], "yearChanges": [],
            "combinations": [{"group": groups[0]["code"], "stratum_type": "overall", "stratum": "all", "combination": "Herb A | Herb B", "combination_size": "2", "patients": groups[0]["patients"], "support_patients": "10", "support": ".25", "stable_core_combination": "True", "bootstrap_core_selection_probability": "1"}],
            "longitudinal": [], "research": {"cohorts": [{"group": "ra_strict", "label": "Rheumatoid arthritis", "patients": "30"}], "nodes": [{"group": "ra_strict", "item_name": "Herb A", "patients": "30", "prevalence": ".5"}], "edges": []}}


class OriginalInteractionTests(unittest.TestCase):
    def test_refresh_replaces_legacy_markup_without_rewriting_aggregate_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = fixture()
            for name in ["primary", "supplement"]:
                (root / (name + ".html")).write_text(HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(original)) + "LEGACY_MARKER", encoding="utf-8")
            build_source_dashboard(root / "primary.html", root / "supplement.html", root / "view.html", refresh_template=True, default_source="primary")
            page = (root / "view.html").read_text(encoding="utf-8")
            self.assertNotIn("LEGACY_MARKER", page)
            self.assertIn('id="view-back"', page)
            block = page.split('<script id="dashboard-data" type="application/json">', 1)[1].split("</script>", 1)[0]
            loaded = json.loads(block)
            self.assertEqual({key: loaded[key] for key in original}, original)
            self.assertIs(loaded["provenance"]["synthetic_mode"], False)

    def test_refresh_does_not_bypass_explicit_synthetic_privacy_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "source.html"
            path.write_text(HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(fixture())), encoding="utf-8")
            for policy in ["conservative-v1", "synthetic-showcase-v1"]:
                with self.subTest(policy=policy), self.assertRaises(DashboardError):
                    build_source_dashboard(path, path, root / "view.html", refresh_template=True, privacy_policy=policy)

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_original_interaction_contract_executes_with_fabricated_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, payload in [("primary", fixture()), ("supplement", fixture(True))]:
                (root / (name + ".html")).write_text(HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload)), encoding="utf-8")
            build_source_dashboard(root / "primary.html", root / "supplement.html", root / "view.html", refresh_template=True, default_source="primary")
            result = subprocess.run(["node", str(Path(__file__).with_name("original_interaction_checks.mjs")), str(root / "view.html")], capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
