from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from datetime import date
from pathlib import Path

from mingyirx.analysis import (
    PrescriptionVisit,
    VisitBuildResult,
    _MatchedTransition,
    _binomial_survival_probability,
    _clinical_patient_year_rows,
    _longitudinal_item_change_rows,
    _matched_control_distribution,
    _matched_reference_rows,
    _matched_sensitivity_rows,
    analyze_clinical_phenotypes,
    transition_metrics,
)
from mingyirx.cohort import ClinicalPhenotypeCohortResult
from mingyirx.config import ConfigError, load_config
from mingyirx.dashboard import build_dashboard
from mingyirx.io import InputError, PatientDemographics, read_sources
from mingyirx.pipeline import TABLE_FIELDS, run_pipeline, validate_pipeline
from mingyirx.privacy import FORBIDDEN_PUBLIC_HEADERS, scan_public_outputs


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "example.json"
INPUT = ROOT / "data" / "synthetic" / "prescriptions.csv"


class PipelineTests(unittest.TestCase):
    @staticmethod
    def _visit(
        patient_id: str,
        visit_id: str,
        visit_date: date,
        items: set[str],
        physician_id: str = "D1",
        group: str = "ra",
        dose_overrides: dict[str, tuple[float, str] | None] | None = None,
    ) -> PrescriptionVisit:
        doses = {item: (1.0, "g") for item in items}
        if dose_overrides:
            doses.update(dose_overrides)
        return PrescriptionVisit(
            patient_id=patient_id,
            group=group,
            visit_id=visit_id,
            visit_date=visit_date,
            physician_id=physician_id,
            items=frozenset(items),
            doses=doses,
            dose_resolved=all(value is not None for value in doses.values()),
        )

    def test_validation_and_exclusive_groups(self) -> None:
        context = validate_pipeline(CONFIG, INPUT)
        self.assertEqual(context.read_result.row_count, 60)
        self.assertEqual(context.cohort_result.total_patients, 14)
        self.assertEqual(len(context.cohort_result.patient_groups), 12)
        self.assertEqual(context.cohort_result.overlap_patients, 1)
        self.assertEqual(context.cohort_result.unmatched_patients, 1)
        self.assertEqual(context.cohort_result.group_counts, {"ra": 4, "sjd": 4, "as": 4})

    def test_transition_metrics(self) -> None:
        context = validate_pipeline(CONFIG, INPUT)
        r1 = context.visit_result.visits_by_patient["R1"]
        r1_metric = transition_metrics(r1[0], r1[1])
        self.assertTrue(math.isclose(r1_metric.jaccard, 0.5))
        self.assertTrue(math.isclose(r1_metric.modification_burden, 0.5))
        self.assertEqual(r1_metric.mode, "composition_only")

        r3 = context.visit_result.visits_by_patient["R3"]
        r3_metric = transition_metrics(r3[0], r3[1])
        self.assertTrue(math.isclose(r3_metric.jaccard, 1.0))
        self.assertTrue(math.isclose(r3_metric.modification_burden, 0.5))
        self.assertEqual(r3_metric.mode, "dose_only")

        unresolved = PrescriptionVisit(
            patient_id="P",
            group="ra",
            visit_id="V",
            visit_date=date(2020, 1, 1),
            physician_id="D1",
            items=frozenset({"A"}),
            doses={"A": None},
            dose_resolved=False,
        )
        unresolved_metric = transition_metrics(unresolved, unresolved)
        self.assertEqual(unresolved_metric.mode, "dose_unresolved")
        self.assertIsNone(unresolved_metric.modification_burden)

    def test_end_to_end_outputs_are_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            manifest = run_pipeline(CONFIG, INPUT, output)
            self.assertEqual(manifest["gate"], "PASS_WITH_WARNINGS")
            self.assertEqual(manifest["privacy_scan"]["issues"], [])
            self.assertEqual(manifest["privacy_scan"]["files_scanned"], 19)
            self.assertEqual(len(manifest["inputs"]), 1)
            self.assertEqual(manifest["input_reconciliation"]["raw_rows"], 60)
            self.assertEqual(manifest["input_reconciliation"]["analysis_rows"], 60)

            expected = {
                "cohort_summary.csv",
                "first_prescription_item_prevalence.csv",
                "frequent_item_combinations.csv",
                "network_nodes.csv",
                "network_edges.csv",
                "network_threshold_sensitivity.csv",
                "network_group_overlap.csv",
                "network_membership.csv",
                "longitudinal_summary.csv",
                "transition_mode_summary.csv",
                "longitudinal_item_change_tendency.csv",
                "cross_group_similarity.csv",
                "temporal_stability.csv",
                "temporal_cutpoint_sensitivity.csv",
                "matched_reference_summary.csv",
                "matched_reference_sensitivity.csv",
                "item_normalization_audit.csv",
                "dose_conflict_audit.csv",
                "report.md",
                "run_manifest.json",
            }
            self.assertEqual({path.name for path in output.iterdir()}, expected)
            self.assertEqual(scan_public_outputs(output).issues, ())

            for path in output.glob("*.csv"):
                with path.open("r", encoding="utf-8", newline="") as handle:
                    headers = {header.casefold() for header in next(csv.reader(handle))}
                self.assertFalse(headers & FORBIDDEN_PUBLIC_HEADERS)

            all_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
            self.assertNotIn("R1,RV01", all_text)
            self.assertNotIn("S1,SV01", all_text)

            with (output / "cross_group_similarity.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            ra_sjd = next(row for row in rows if row["group_left"] == "ra" and row["group_right"] == "sjd")
            self.assertEqual(int(ra_sjd["common_public_items"]), 2)
            self.assertTrue(math.isclose(float(ra_sjd["weighted_jaccard"]), 6 / 7))

            with (output / "temporal_cutpoint_sensitivity.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                temporal_rows = list(csv.DictReader(handle))
            self.assertEqual(len(temporal_rows), 12)
            ra_2018 = next(
                row
                for row in temporal_rows
                if row["group"] == "ra" and row["early_end_year"] == "2018"
            )
            self.assertEqual(ra_2018["early_patients"], "")
            self.assertEqual(ra_2018["late_patients"], "")
            report_text = (output / "report.md").read_text(encoding="utf-8")
            self.assertNotIn("early=1", report_text)
            self.assertIn("Common2 \\| Fuling", report_text)

            with (output / "item_normalization_audit.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                normalization_row = next(csv.DictReader(handle))
            self.assertEqual(
                normalization_row["dictionary_version"], "synthetic-reviewed-v1"
            )
            self.assertEqual(normalization_row["unmapped_source_items"], "0")
            self.assertEqual(normalization_row["changed_item_lines"], "0")

            with (output / "frequent_item_combinations.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                combination_rows = list(csv.DictReader(handle))
            ra_pair = next(
                row
                for row in combination_rows
                if row["group"] == "ra"
                and row["combination"] == "Common2 | Fuling"
            )
            self.assertEqual(ra_pair["support_patients"], "2")
            self.assertTrue(math.isclose(float(ra_pair["support"]), 0.5))
            self.assertTrue(math.isclose(float(ra_pair["lift"]), 2.0))
            self.assertTrue(
                math.isclose(
                    float(ra_pair["bootstrap_core_selection_probability"]),
                    11 / 16,
                )
            )
            self.assertEqual(ra_pair["stable_core_combination"], "False")

            with (output / "network_threshold_sensitivity.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                network_rows = list(csv.DictReader(handle))
            self.assertEqual(len(network_rows), 27)
            primary_ra = next(
                row
                for row in network_rows
                if row["group"] == "ra" and row["primary_setting"] == "True"
            )
            self.assertEqual(primary_ra["node_prevalence_threshold"], "0.5")
            self.assertEqual(primary_ra["edge_cosine_threshold"], "0.5")
            self.assertEqual(primary_ra["node_retention_vs_primary"], "1")
            self.assertEqual(primary_ra["node_jaccard_vs_primary"], "1")
            self.assertEqual(primary_ra["edge_jaccard_vs_primary"], "")

            with (output / "network_nodes.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                network_nodes = list(csv.DictReader(handle))
            self.assertTrue(network_nodes)
            self.assertTrue(
                all(
                    int(row["exposed_patients"]) >= 2
                    and float(row["bootstrap_core_selection_probability"]) >= 0.8
                    for row in network_nodes
                )
            )

            with (output / "network_edges.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                network_edges = list(csv.DictReader(handle))
            self.assertTrue(network_edges)
            self.assertTrue(
                all(
                    int(row["cooccurrence_patients"]) >= 2
                    and float(row["cosine_similarity"]) >= 0.5
                    for row in network_edges
                )
            )

            with (output / "network_group_overlap.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                network_overlap = list(csv.DictReader(handle))
            sjd_as = next(
                row
                for row in network_overlap
                if row["group_left"] == "sjd" and row["group_right"] == "as"
            )
            self.assertEqual(sjd_as["common_nodes"], "2")
            self.assertEqual(sjd_as["node_jaccard"], "1")
            self.assertEqual(sjd_as["common_edges"], "1")
            self.assertEqual(sjd_as["edge_jaccard"], "1")

            with (output / "network_membership.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                network_membership = list(csv.DictReader(handle))
            shared_node = next(
                row
                for row in network_membership
                if row["member_type"] == "node" and row["member"] == "Shared"
            )
            self.assertEqual(shared_node["groups_present"], "ra;sjd;as")
            self.assertEqual(shared_node["membership_class"], "all_groups")
            shared_edge = next(
                row
                for row in network_membership
                if row["member_type"] == "edge"
                and row["member"] == "Common2 | Shared"
            )
            self.assertEqual(shared_edge["groups_present"], "sjd;as")
            self.assertEqual(shared_edge["membership_class"], "multi_group")

            repeated_manifest = run_pipeline(CONFIG, INPUT, output)
            self.assertEqual(repeated_manifest["privacy_scan"]["files_scanned"], 19)
            self.assertEqual(repeated_manifest["artifacts"], manifest["artifacts"])

            dashboard = output / "dashboard.html"
            dashboard_summary = build_dashboard(
                output, dashboard, "Synthetic </script><script>alert(1)</script>"
            )
            dashboard_text = dashboard.read_text(encoding="utf-8")
            self.assertEqual(dashboard_summary["gate"], "PASS")
            self.assertFalse(dashboard_summary["patient_level_data_included"])
            self.assertIn("处方记录复盘", dashboard_text)
            self.assertIn("模拟数据演示", dashboard_text)
            self.assertNotIn("从真实门诊记录", dashboard_text)
            self.assertIn("&lt;/script&gt;", dashboard_text)
            self.assertNotIn("</script><script>alert(1)</script>", dashboard_text)
            self.assertNotIn("patient_id", dashboard_text)
            first_dashboard = dashboard.read_bytes()
            build_dashboard(
                output, dashboard, "Synthetic </script><script>alert(1)</script>"
            )
            self.assertEqual(dashboard.read_bytes(), first_dashboard)

    def test_item_change_tendency_is_patient_equal_and_direction_suppressed(self) -> None:
        visits = {
            "P1": (
                self._visit("P1", "P1V1", date(2020, 1, 1), {"A"}),
                self._visit("P1", "P1V2", date(2020, 2, 1), {"A", "B"}),
            ),
            "P2": (
                self._visit("P2", "P2V1", date(2020, 1, 1), {"A"}),
                self._visit("P2", "P2V2", date(2020, 2, 1), {"A", "B"}),
            ),
            "P3": (
                self._visit("P3", "P3V1", date(2020, 1, 1), {"A", "B"}),
                self._visit("P3", "P3V2", date(2020, 2, 1), {"A"}),
            ),
        }
        rows = _longitudinal_item_change_rows(visits, ("ra",), 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_name"], "B")
        self.assertEqual(rows[0]["change_type"], "addition")
        self.assertEqual(rows[0]["repeat_patients"], 3)
        self.assertEqual(rows[0]["patients_with_change"], 2)
        self.assertTrue(math.isclose(float(rows[0]["patient_prevalence"]), 2 / 3))
        self.assertTrue(
            math.isclose(
                float(rows[0]["mean_patient_transition_fraction"]), 2 / 3
            )
        )
        self.assertEqual(rows[0]["dose_patients"], 2)
        self.assertEqual(rows[0]["most_common_dose_values_g"], "1")
        self.assertEqual(rows[0]["most_common_dose_patients"], 2)
        self.assertEqual(rows[0]["most_common_dose_fraction"], 1.0)
        self.assertFalse(rows[0]["most_common_dose_tied"])

        unresolved_visits = {
            **visits,
            "P2": (
                self._visit("P2", "P2V1", date(2020, 1, 1), {"A"}),
                self._visit(
                    "P2",
                    "P2V2",
                    date(2020, 2, 1),
                    {"A", "B"},
                    dose_overrides={"B": None},
                ),
            ),
        }
        unresolved_rows = _longitudinal_item_change_rows(
            unresolved_visits, ("ra",), 2
        )
        self.assertIsNone(unresolved_rows[0]["dose_patients"])
        self.assertIsNone(unresolved_rows[0]["most_common_dose_values_g"])

    def test_clinical_phenotypes_are_stratified_and_compared_after_suppression(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_data = json.loads(CONFIG.read_text(encoding="utf-8"))
            config_data["columns"].update(
                {"sex": "sex", "birth_date": "birth_date"}
            )
            config_data["item_normalization"] = {
                "version": "source-string-test",
                "dictionary_path": None,
                "expected_sha256": None,
            }
            config_data["clinical_phenotype_analysis"] = {
                "enabled": True,
                "other_exclude_patterns": ["\\bSLE\\b"],
                "sex_categories": [
                    {"name": "female", "label": "Female", "source_values": ["F"]},
                    {"name": "male", "label": "Male", "source_values": ["M"]},
                ],
                "age_bands": [
                    {"name": "under_40", "label": "<40", "min_age": 0, "max_age": 39},
                    {"name": "40_59", "label": "40-59", "min_age": 40, "max_age": 59},
                    {"name": "60_plus", "label": "60+", "min_age": 60, "max_age": 120},
                ],
            }
            config_path = Path(temporary) / "clinical.json"
            config_path.write_text(json.dumps(config_data), encoding="utf-8")
            config = load_config(config_path)

        visits: dict[str, tuple[PrescriptionVisit, ...]] = {}
        demographics: dict[str, PatientDemographics] = {}
        groups = {
            "ra": ("ra",),
            "sjd": ("sjd",),
            "ra__sjd": ("ra", "sjd"),
        }
        for group, prefix in (("ra", "R"), ("sjd", "S"), ("ra__sjd", "C")):
            for index in range(1, 4):
                patient_id = f"{prefix}{index}"
                adds_item = index <= 2 or group == "ra__sjd"
                visits[patient_id] = (
                    self._visit(
                        patient_id,
                        f"{patient_id}V1",
                        date(2020, 1, 1),
                        {"A"},
                        group=group,
                    ),
                    self._visit(
                        patient_id,
                        f"{patient_id}V2",
                        date(2020, 2, 1),
                        {"A", "B"} if adds_item else {"A"},
                        group=group,
                    ),
                )
                demographics[patient_id] = PatientDemographics(
                    sex="female" if index <= 2 else "male",
                    birth_date=date(1990, 1, 1) if index <= 2 else date(1950, 1, 1),
                )

        visit_result = VisitBuildResult(
            visits_by_patient=visits,
            dose_conflict_item_count=0,
            dose_conflict_patients_by_group={},
            dose_conflict_visits_by_group={},
            dose_conflict_items_by_group={},
            eligible_item_line_count=0,
            ineligible_item_line_count=0,
            group_mismatch_visit_count=0,
            empty_eligible_visit_count=0,
            dictionary_matched_item_line_count=0,
            changed_item_line_count=0,
            distinct_source_item_count=2,
            dictionary_matched_source_item_count=0,
            canonical_item_count=2,
            canonical_collision_visit_item_count=0,
            warnings=(),
        )
        cohort = ClinicalPhenotypeCohortResult(
            patient_groups={patient: rows[0].group for patient, rows in visits.items()},
            group_components=groups,
            group_labels={
                "ra": "RA",
                "sjd": "SjD",
                "ra__sjd": "RA + SjD",
            },
            group_counts={group: 3 for group in groups},
            target_patients=9,
            other_disease_excluded_patients=0,
            warnings=(),
        )
        result = analyze_clinical_phenotypes(
            visit_result, cohort, demographics, config
        )
        summary = result.tables["clinical_phenotype_summary"]
        self.assertFalse(any(row["stratum"] == "male" for row in summary))
        overall_difference = next(
            row
            for row in result.tables["clinical_item_change_comparison"]
            if row["combination_group"] == "ra__sjd"
            and row["single_group"] == "ra"
            and row["stratum_type"] == "overall"
            and row["item_name"] == "B"
        )
        self.assertTrue(
            math.isclose(float(overall_difference["prevalence_difference"]), 1 / 3)
        )
        self.assertTrue(
            math.isclose(
                float(overall_difference["mean_transition_fraction_difference"]),
                1 / 3,
            )
        )
        self.assertEqual(overall_difference["higher_frequency"], "combination")
        self.assertEqual(overall_difference["combination_dose_patients"], 3)
        self.assertEqual(
            overall_difference["combination_most_common_dose_values_g"], "1"
        )
        self.assertEqual(
            overall_difference["combination_most_common_dose_patients"], 3
        )
        self.assertEqual(overall_difference["single_dose_patients"], 2)
        self.assertEqual(
            overall_difference["single_most_common_dose_values_g"], "1"
        )

        year_summary = result.tables["clinical_year_summary"]
        self.assertTrue(
            any(
                row["group"] == "ra__sjd"
                and row["stratum_type"] == "overall"
                and row["year"] == 2020
                and row["patients"] == 3
                and row["transitions"] == 3
                for row in year_summary
            )
        )

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "outputs"
            run_pipeline(CONFIG, INPUT, output)
            for table_name, rows in result.tables.items():
                with (output / f"{table_name}.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=TABLE_FIELDS[table_name],
                        extrasaction="ignore",
                    )
                    writer.writeheader()
                    writer.writerows(rows)
            dashboard_path = output / "clinical_review.html"
            dashboard = build_dashboard(output, dashboard_path, "Clinical test")
            dashboard_text = dashboard_path.read_text(encoding="utf-8")
            self.assertTrue(dashboard["clinical_mode"])
            self.assertIn("同类历史处方参照", dashboard_text)
            self.assertIn("年度处方演变", dashboard_text)
            self.assertIn('class="annual-line-chart"', dashboard_text)
            self.assertIn("annualLineSegments", dashboard_text)
            self.assertIn("endYear-startYear+1", dashboard_text)
            self.assertIn("断线＝未公开或未达到门槛", dashboard_text)
            self.assertNotIn("annual-bar-area", dashboard_text)
            self.assertIn("减味 ←", dashboard_text)
            self.assertIn('grid-template-areas:"removal core addition"', dashboard_text)
            self.assertIn("发生患者占比", dashboard_text)
            self.assertIn("最常记录克数", dashboard_text)

    def test_change_dose_mode_is_patient_equal_and_reports_group_ties(self) -> None:
        visits = {
            "P1": (
                self._visit("P1", "P1V1", date(2021, 1, 1), {"A"}),
                self._visit(
                    "P1",
                    "P1V2",
                    date(2021, 2, 1),
                    {"A", "B"},
                    dose_overrides={"B": (2.0, "g")},
                ),
                self._visit("P1", "P1V3", date(2021, 3, 1), {"A"}),
                self._visit(
                    "P1",
                    "P1V4",
                    date(2021, 4, 1),
                    {"A", "B"},
                    dose_overrides={"B": (4.0, "g")},
                ),
                self._visit("P1", "P1V5", date(2021, 5, 1), {"A"}),
                self._visit(
                    "P1",
                    "P1V6",
                    date(2021, 6, 1),
                    {"A", "B"},
                    dose_overrides={"B": (2.0, "g")},
                ),
            ),
            "P2": (
                self._visit("P2", "P2V1", date(2021, 1, 1), {"A"}),
                self._visit(
                    "P2",
                    "P2V2",
                    date(2021, 2, 1),
                    {"A", "B"},
                    dose_overrides={"B": (40.0, "g")},
                ),
            ),
            "P3": (
                self._visit("P3", "P3V1", date(2021, 1, 1), {"A"}),
                self._visit(
                    "P3",
                    "P3V2",
                    date(2021, 2, 1),
                    {"A", "B"},
                    dose_overrides={"B": (5.0, "g")},
                ),
                self._visit("P3", "P3V3", date(2021, 3, 1), {"A"}),
                self._visit(
                    "P3",
                    "P3V4",
                    date(2021, 4, 1),
                    {"A", "B"},
                    dose_overrides={"B": (6.0, "g")},
                ),
            ),
        }
        rows = _longitudinal_item_change_rows(visits, ("ra",), 1)
        addition_b = next(
            row
            for row in rows
            if row["item_name"] == "B" and row["change_type"] == "addition"
        )
        self.assertEqual(addition_b["dose_patients"], 2)
        self.assertEqual(addition_b["most_common_dose_values_g"], "2;40")
        self.assertEqual(addition_b["most_common_dose_patients"], 1)
        self.assertEqual(addition_b["most_common_dose_fraction"], 0.5)
        self.assertTrue(addition_b["most_common_dose_tied"])
        self.assertEqual(addition_b["patients_with_change"], 3)

        privacy_suppressed = _longitudinal_item_change_rows(
            visits, ("ra",), 2
        )
        suppressed_addition_b = next(
            row
            for row in privacy_suppressed
            if row["item_name"] == "B" and row["change_type"] == "addition"
        )
        self.assertIsNone(suppressed_addition_b["dose_patients"])
        self.assertIsNone(
            suppressed_addition_b["most_common_dose_values_g"]
        )

        _, _, annual_changes = _clinical_patient_year_rows(
            visits, ("ra",), 1
        )
        annual_addition_b = next(
            row
            for row in annual_changes
            if row["item_name"] == "B" and row["change_type"] == "addition"
        )
        self.assertEqual(annual_addition_b["dose_patients"], 2)
        self.assertEqual(
            annual_addition_b["most_common_dose_values_g"], "2;40"
        )
        self.assertTrue(annual_addition_b["most_common_dose_tied"])

    def test_patient_year_changes_are_assigned_to_the_later_visit_year(self) -> None:
        visits = {
            patient_id: (
                self._visit(
                    patient_id,
                    f"{patient_id}V1",
                    date(2020, 12, 20),
                    {"A"},
                ),
                self._visit(
                    patient_id,
                    f"{patient_id}V2",
                    date(2021, 1, 10),
                    {"A", "B"},
                ),
            )
            for patient_id in ("P1", "P2")
        }
        summary, items, changes = _clinical_patient_year_rows(
            visits, ("ra",), 2
        )
        year_2020 = next(row for row in summary if row["year"] == 2020)
        year_2021 = next(row for row in summary if row["year"] == 2021)
        self.assertEqual(year_2020["repeat_patients"], 0)
        self.assertEqual(year_2020["transitions"], 0)
        self.assertEqual(year_2021["repeat_patients"], 2)
        self.assertEqual(year_2021["transitions"], 2)
        item_b = next(
            row for row in items if row["year"] == 2021 and row["item_name"] == "B"
        )
        self.assertTrue(math.isclose(float(item_b["prevalence"]), 1.0))
        self.assertEqual(item_b["dose_patients"], 2)
        self.assertEqual(item_b["most_common_dose_values_g"], "1")
        self.assertEqual(item_b["most_common_dose_patients"], 2)
        addition_b = next(
            row
            for row in changes
            if row["year"] == 2021
            and row["item_name"] == "B"
            and row["change_type"] == "addition"
        )
        self.assertTrue(
            math.isclose(
                float(addition_b["mean_patient_transition_fraction"]), 1.0
            )
        )
        self.assertEqual(addition_b["dose_patients"], 2)
        self.assertEqual(addition_b["most_common_dose_values_g"], "1")
        self.assertEqual(addition_b["most_common_dose_patients"], 2)

    def test_exact_bootstrap_core_selection_probability(self) -> None:
        self.assertTrue(
            math.isclose(
                _binomial_survival_probability(4, 0.5, 2),
                11 / 16,
            )
        )
        self.assertEqual(_binomial_survival_probability(4, 1.0, 2), 1.0)
        large_sample_probability = _binomial_survival_probability(5000, 0.5, 2500)
        self.assertGreater(large_sample_probability, 0.5)
        self.assertLess(large_sample_probability, 0.51)

    def test_combination_sizes_are_restricted_to_pairs_and_triplets(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config["combination_analysis"]["sizes"] = [1, 2]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid_combinations.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_network_threshold_grid_must_include_primary_setting(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config["network_analysis"]["edge_cosine_thresholds"] = [0.3, 0.7]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid_network.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_real_configuration_rejects_low_public_threshold(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config["synthetic_mode"] = False
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "unsafe.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_temporal_cutpoints_must_include_primary_year(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config["temporal_cutpoints"] = [2018, 2020]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid_cutpoints.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_privacy_scan_does_not_treat_decimal_precision_as_an_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            (output / "aggregate.csv").write_text(
                "metric,value\nprevalence,0.060561299852289516\n", encoding="utf-8"
            )
            self.assertEqual(scan_public_outputs(output).issues, ())

    def test_positional_multi_file_mapping_preserves_within_file_multiplicity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            first = temporary_root / "first.csv"
            second = temporary_root / "second.csv"
            header = ["patient", "visit", "when", "diagnosis", "item", "dose", "unit", "visit"]
            overlapping = ["P1", "V1", "2019-01-01", "RA", "A", "10", "g", "duplicate header"]
            with first.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                writer.writerow(overlapping)
                writer.writerow(overlapping)
                writer.writerow(["P2", "V2", "2020-01-01", "SjD", "B", "8", "g", "x"])
            with second.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                writer.writerow(overlapping)
                writer.writerow(["P3", "V3", "2021-01-01", "AS", "C", "6", "g", "x"])

            config_data = json.loads(CONFIG.read_text(encoding="utf-8"))
            config_data["encoding"] = "utf-8"
            config_data["item_normalization"] = {
                "version": "source-string-test-v1",
                "dictionary_path": None,
            }
            config_data["cross_file_overlap_policy"] = "max_multiplicity"
            config_data["columns"] = {
                "patient_id": 0,
                "visit_id": 1,
                "visit_date": 2,
                "diagnosis_text": 3,
                "item_name": 4,
                "dose": 5,
                "unit": 6,
            }
            config_path = temporary_root / "config.json"
            config_path.write_text(json.dumps(config_data), encoding="utf-8")
            config = load_config(config_path)

            result = read_sources((first, second), config)
            self.assertEqual(result.row_count, 5)
            self.assertEqual(result.analysis_row_count, 4)
            self.assertEqual(result.cross_file_overlap_rows_detected, 1)
            self.assertEqual(result.cross_file_overlap_rows_removed, 1)
            self.assertEqual(result.duplicate_line_count, 1)
            self.assertEqual(len(result.source_files), 2)
            self.assertEqual(result.source_files[0].duplicate_header_names, ("visit",))

            config_data["columns"]["visit_id"] = "visit"
            ambiguous_path = temporary_root / "ambiguous.json"
            ambiguous_path.write_text(json.dumps(config_data), encoding="utf-8")
            with self.assertRaises(InputError):
                read_sources((first, second), load_config(ambiguous_path))

            config_data["columns"]["visit_id"] = 1
            config_data["expected_input_sha256"] = {
                "first.csv": "0" * 64,
                "second.csv": "0" * 64,
            }
            mismatched_path = temporary_root / "mismatched-hash.json"
            mismatched_path.write_text(json.dumps(config_data), encoding="utf-8")
            with self.assertRaises(InputError):
                read_sources((first, second), load_config(mismatched_path))

    def test_visit_group_and_item_eligibility_are_applied_after_cohort_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            source = temporary_root / "eligibility.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "patient_id",
                        "visit_id",
                        "visit_date",
                        "diagnosis_text",
                        "item_name",
                        "dose",
                        "unit",
                        "physician_id",
                    ]
                )
                writer.writerows(
                    [
                        ["P1", "V1", "2019-01-01", "RA", "A", "10", "g", "D1"],
                        ["P1", "V2", "2020-01-01", "Other", "A", "10", "g", "D1"],
                        ["P1", "V3", "2021-01-01", "RA", "Tablet", "1", "tablet", "D1"],
                        ["P2", "V1", "2019-01-01", "SjD", "B", "8", "g", "D1"],
                        ["P3", "V1", "2019-01-01", "AS", "C", "6", "g", "D1"],
                    ]
                )

            config_data = json.loads(CONFIG.read_text(encoding="utf-8"))
            config_data["encoding"] = "utf-8"
            config_data["item_normalization"] = {
                "version": "source-string-test-v1",
                "dictionary_path": None,
            }
            config_data["require_visit_group_match"] = True
            config_data["item_eligibility"] = {
                "allowed_units": ["g"],
                "excluded_exact_names": [],
                "excluded_name_patterns": [],
            }
            config_path = temporary_root / "eligibility.json"
            config_path.write_text(json.dumps(config_data), encoding="utf-8")

            context = validate_pipeline(config_path, source)
            self.assertEqual(context.cohort_result.total_patients, 3)
            self.assertEqual(len(context.cohort_result.patient_groups), 3)
            self.assertEqual(context.visit_result.group_mismatch_visit_count, 1)
            self.assertEqual(context.visit_result.ineligible_item_line_count, 1)
            self.assertEqual(context.visit_result.empty_eligible_visit_count, 1)
            self.assertEqual(len(context.visit_result.visits_by_patient["P1"]), 1)

    def test_item_dictionary_mapping_can_expose_a_post_mapping_dose_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            dictionary = temporary_root / "dictionary.csv"
            with dictionary.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["source_item_name", "canonical_item_name"])
                writer.writerow(["Fu Ling", "茯苓"])
                writer.writerow(["茯苓", "茯苓"])

            source = temporary_root / "source.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "patient_id",
                        "visit_id",
                        "visit_date",
                        "diagnosis_text",
                        "item_name",
                        "dose",
                        "unit",
                        "physician_id",
                    ]
                )
                writer.writerows(
                    [
                        ["P1", "V1", "2019-01-01", "RA", "Fu Ling", "10", "g", "D1"],
                        ["P1", "V1", "2019-01-01", "RA", "茯苓", "12", "g", "D1"],
                        ["P4", "V1", "2019-01-01", "RA", "Fu Ling", "10", "g", "D1"],
                        ["P4", "V1", "2019-01-01", "RA", "茯苓", "12", "g", "D1"],
                        ["P2", "V1", "2019-01-01", "SjD", "Fu Ling", "10", "g", "D1"],
                        ["P2", "V1", "2019-01-01", "SjD", "茯苓", "12", "g", "D1"],
                        ["P3", "V1", "2019-01-01", "AS", "C", "6", "g", "D1"],
                    ]
                )

            config_data = json.loads(CONFIG.read_text(encoding="utf-8"))
            config_data["encoding"] = "utf-8"
            config_data["item_normalization"] = {
                "version": "test-reviewed-v1",
                "dictionary_path": "dictionary.csv",
            }
            config_path = temporary_root / "config.json"
            config_path.write_text(json.dumps(config_data), encoding="utf-8")

            context = validate_pipeline(config_path, source)
            audit = context.visit_result
            self.assertEqual(audit.dictionary_matched_item_line_count, 6)
            self.assertEqual(audit.changed_item_line_count, 3)
            self.assertEqual(audit.distinct_source_item_count, 3)
            self.assertEqual(audit.dictionary_matched_source_item_count, 2)
            self.assertEqual(audit.canonical_item_count, 2)
            self.assertEqual(audit.canonical_collision_visit_item_count, 3)
            self.assertEqual(audit.dose_conflict_item_count, 3)
            self.assertEqual(
                audit.dose_conflict_patients_by_group, {"ra": 2, "sjd": 1}
            )
            mapped_visit = audit.visits_by_patient["P1"][0]
            self.assertEqual(mapped_visit.items, frozenset({"茯苓"}))
            self.assertFalse(mapped_visit.dose_resolved)

            output = temporary_root / "output"
            manifest = run_pipeline(config_path, source, output)
            self.assertIn(
                "Dose conflicts were found; see the aggregate dose-conflict audit",
                manifest["warnings"],
            )
            with (output / "dose_conflict_audit.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            ra_row = next(row for row in rows if row["group"] == "ra")
            self.assertEqual(ra_row["patients_with_conflict"], "")
            self.assertEqual(ra_row["visit_item_conflicts"], "")
            all_row = next(row for row in rows if row["group"] == "all")
            self.assertEqual(all_row["patients_with_conflict"], "")
            self.assertEqual(all_row["visit_item_conflicts"], "")

            config_data["item_normalization"]["expected_sha256"] = "0" * 64
            mismatched_path = temporary_root / "mismatched_dictionary.json"
            mismatched_path.write_text(json.dumps(config_data), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(mismatched_path)

    def test_matched_reference_excludes_self_and_uses_nearest_size_fallback(self) -> None:
        config = load_config(CONFIG)
        exact_visits = {
            "P1": (
                self._visit("P1", "P1V1", date(2020, 1, 1), {"A"}),
                self._visit("P1", "P1V2", date(2020, 2, 1), {"A"}),
            ),
            "P2": (
                self._visit("P2", "P2V1", date(2020, 1, 1), {"B"}),
                self._visit("P2", "P2V2", date(2020, 2, 1), {"B"}),
            ),
        }
        rows, sensitivity_rows, metadata, warnings = _matched_reference_rows(
            exact_visits, config
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["patients"], 2)
        self.assertEqual(rows[0]["matched_transitions"], 2)
        self.assertEqual(rows[0]["unmatched_transitions"], 0)
        self.assertTrue(math.isclose(rows[0]["observed_patient_median_jaccard"], 1.0))
        self.assertTrue(
            math.isclose(rows[0]["matched_between_patient_median_jaccard"], 0.0)
        )
        self.assertTrue(math.isclose(rows[0]["within_minus_between_median"], 1.0))
        self.assertTrue(
            math.isclose(rows[0]["exact_year_stage_size_match_pct"], 100.0)
        )
        self.assertEqual(metadata["matched_patients"], 2)
        self.assertEqual(metadata["sensitivity_seed"], 20260824)
        exact_sensitivity = next(
            row
            for row in sensitivity_rows
            if row["analysis"] == "exact_year_stage_size_only"
            and row["group"] == "ra"
        )
        self.assertEqual(exact_sensitivity["patients"], 2)
        self.assertEqual(exact_sensitivity["transitions"], 2)
        self.assertTrue(
            math.isclose(exact_sensitivity["within_minus_between_median"], 1.0)
        )
        self.assertEqual(
            (rows, sensitivity_rows, metadata, warnings),
            _matched_reference_rows(exact_visits, config),
        )

        fallback_visits = {
            "P1": (
                self._visit("P1", "P1V1", date(2020, 1, 1), {"A"}),
                self._visit("P1", "P1V2", date(2020, 2, 1), {"A", "C"}),
            ),
            "P2": (
                self._visit("P2", "P2V1", date(2020, 1, 1), {"B"}),
                self._visit("P2", "P2V2", date(2020, 2, 1), {"B"}),
            ),
        }
        fallback_rows, fallback_sensitivity, _, _ = _matched_reference_rows(
            fallback_visits, config
        )
        self.assertTrue(
            math.isclose(fallback_rows[0]["exact_year_stage_size_match_pct"], 0.0)
        )
        self.assertTrue(math.isclose(fallback_rows[0]["matchable_transition_pct"], 100.0))
        self.assertFalse(
            any(
                row["analysis"] == "exact_year_stage_size_only"
                and row["group"] == "ra"
                for row in fallback_sensitivity
            )
        )

        missing_physician_visits = {
            patient: tuple(
                self._visit(
                    visit.patient_id,
                    visit.visit_id,
                    visit.visit_date,
                    set(visit.items),
                    physician_id="",
                )
                for visit in visits
            )
            for patient, visits in exact_visits.items()
        }
        with self.assertRaises(InputError):
            _matched_reference_rows(missing_physician_visits, config)

    def test_matched_reference_weights_control_patients_before_visits(self) -> None:
        previous = self._visit("INDEX", "V1", date(2020, 1, 1), {"A"})
        candidates = [
            self._visit("CONTROL1", "C1V1", date(2020, 2, 1), {"A"}),
            self._visit("CONTROL1", "C1V2", date(2020, 3, 1), {"A"}),
            self._visit("CONTROL1", "C1V3", date(2020, 4, 1), {"A"}),
            self._visit("CONTROL2", "C2V1", date(2020, 2, 1), {"B"}),
        ]
        matched, control_values = _matched_control_distribution(previous, candidates)
        self.assertEqual(len(control_values), 2)
        self.assertTrue(math.isclose(matched, 0.5))

    def test_matched_sensitivity_requires_five_control_patients(self) -> None:
        config = load_config(CONFIG)

        def transition(control_patient_n: int) -> _MatchedTransition:
            return _MatchedTransition(
                observed_jaccard=0.8,
                matched_between_jaccard=0.3,
                control_patient_n=control_patient_n,
                match_level="nearest_size_same_year_stage",
                control_values_by_patient=((0.3,),),
            )

        transitions_by_group = {
            "ra": {
                "P1": [transition(4), transition(5)],
                "P2": [transition(5)],
            },
            "sjd": {},
            "as": {},
        }
        rows, _ = _matched_sensitivity_rows(transitions_by_group, config)
        minimum_five = next(
            row
            for row in rows
            if row["analysis"] == "minimum_5_control_patients"
            and row["group"] == "ra"
        )
        self.assertEqual(minimum_five["patients"], 2)
        self.assertEqual(minimum_five["transitions"], 2)


if __name__ == "__main__":
    unittest.main()
