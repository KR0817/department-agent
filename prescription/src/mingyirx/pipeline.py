from __future__ import annotations

import csv
import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from . import __version__
from .analysis import (
    AnalysisResult,
    VisitBuildResult,
    analyze,
    analyze_clinical_phenotypes,
    build_visits,
)
from .cohort import (
    ClinicalPhenotypeCohortResult,
    CohortResult,
    assign_clinical_phenotypes,
    assign_patient_groups,
    matches_clinical_phenotype_visit,
)
from .config import AnalysisConfig, load_config
from .io import InputError, ReadResult, file_sha256, read_sources
from .privacy import PrivacyScan, scan_public_outputs


TABLE_FIELDS = {
    "cohort_summary": [
        "group",
        "patients",
        "first_prescription_patients",
        "repeat_patients",
        "visits",
        "transitions",
    ],
    "first_prescription_item_prevalence": [
        "group",
        "item_name",
        "exposed_patients",
        "group_patients",
        "prevalence",
        "dose_patients",
        "most_common_dose_values_g",
        "most_common_dose_patients",
        "most_common_dose_fraction",
        "most_common_dose_tied",
    ],
    "frequent_item_combinations": [
        "group",
        "patients",
        "combination_size",
        "combination",
        "support_patients",
        "support",
        "lift",
        "bootstrap_core_selection_probability",
        "stable_core_combination",
    ],
    "network_nodes": [
        "group",
        "group_label",
        "patients",
        "node_prevalence_threshold",
        "edge_cosine_threshold",
        "item_name",
        "exposed_patients",
        "prevalence",
        "bootstrap_core_selection_probability",
        "degree",
        "weighted_degree",
    ],
    "network_edges": [
        "group",
        "group_label",
        "patients",
        "node_prevalence_threshold",
        "edge_cosine_threshold",
        "item_1",
        "item_2",
        "cooccurrence_patients",
        "support",
        "cosine_similarity",
        "lift",
    ],
    "network_threshold_sensitivity": [
        "group",
        "group_label",
        "patients",
        "node_prevalence_threshold",
        "edge_cosine_threshold",
        "stable_nodes",
        "edges",
        "density",
        "connected_components",
        "largest_component_fraction",
        "node_retention_vs_primary",
        "node_jaccard_vs_primary",
        "edge_retention_vs_primary",
        "edge_jaccard_vs_primary",
        "primary_setting",
    ],
    "network_group_overlap": [
        "group_left",
        "group_left_label",
        "group_right",
        "group_right_label",
        "left_nodes",
        "right_nodes",
        "common_nodes",
        "node_jaccard",
        "left_edges",
        "right_edges",
        "common_edges",
        "edge_jaccard",
    ],
    "network_membership": [
        "member_type",
        "member",
        "item_1",
        "item_2",
        "groups_present",
        "group_labels_present",
        "groups_present_n",
        "membership_class",
    ],
    "longitudinal_summary": [
        "group",
        "repeat_patients",
        "transitions",
        "dose_resolved_patients",
        "dose_resolved_transitions",
        "median_patient_jaccard",
        "median_patient_retention",
        "median_patient_addition",
        "median_patient_modification_burden",
    ],
    "transition_mode_summary": [
        "group",
        "mode",
        "dose_resolved_patients",
        "dose_resolved_transitions",
        "mean_patient_proportion",
    ],
    "longitudinal_item_change_tendency": [
        "group",
        "item_name",
        "change_type",
        "repeat_patients",
        "patients_with_change",
        "patient_prevalence",
        "mean_patient_transition_fraction",
        "dose_patients",
        "most_common_dose_values_g",
        "most_common_dose_patients",
        "most_common_dose_fraction",
        "most_common_dose_tied",
    ],
    "cross_group_similarity": [
        "group_left",
        "group_right",
        "common_public_items",
        "weighted_jaccard",
        "jensen_shannon_distance",
    ],
    "temporal_stability": [
        "group",
        "early_end_year",
        "early_patients",
        "late_patients",
        "item_universe_items",
        "weighted_jaccard",
        "jensen_shannon_distance",
        "early_core_items",
        "retained_core_items",
        "core_retention_fraction",
    ],
    "temporal_cutpoint_sensitivity": [
        "group",
        "early_end_year",
        "early_patients",
        "late_patients",
        "item_universe_items",
        "weighted_jaccard",
        "jensen_shannon_distance",
        "early_core_items",
        "retained_core_items",
        "core_retention_fraction",
    ],
    "matched_reference_summary": [
        "group",
        "patients",
        "matched_transitions",
        "potential_transitions",
        "unmatched_transitions",
        "matchable_transition_pct",
        "exact_year_stage_size_match_pct",
        "eligible_control_patients_median",
        "observed_patient_median_jaccard",
        "observed_bootstrap_ci95_low",
        "observed_bootstrap_ci95_high",
        "matched_between_patient_median_jaccard",
        "matched_between_bootstrap_ci95_low",
        "matched_between_bootstrap_ci95_high",
        "within_minus_between_median",
        "within_minus_between_bootstrap_ci95_low",
        "within_minus_between_bootstrap_ci95_high",
        "empirical_one_sided_p",
        "empirical_one_sided_bh_fdr",
    ],
    "matched_reference_sensitivity": [
        "analysis",
        "group",
        "patients",
        "transitions",
        "observed_patient_median_jaccard",
        "matched_between_patient_median_jaccard",
        "within_minus_between_median",
        "within_minus_between_bootstrap_ci95_low",
        "within_minus_between_bootstrap_ci95_high",
    ],
    "item_normalization_audit": [
        "dictionary_version",
        "dictionary_sha256",
        "dictionary_entries",
        "eligible_item_lines",
        "distinct_source_items",
        "dictionary_matched_item_lines",
        "dictionary_matched_source_items",
        "unmapped_source_items",
        "changed_item_lines",
        "canonical_items",
        "canonical_collision_visit_items",
    ],
    "dose_conflict_audit": [
        "group",
        "patients",
        "visits",
        "patients_with_conflict",
        "visits_with_conflict",
        "visit_item_conflicts",
        "patients_with_conflict_pct",
        "visits_with_conflict_pct",
    ],
    "clinical_phenotype_summary": [
        "group",
        "group_label",
        "components",
        "disease_count",
        "stratum_type",
        "stratum",
        "stratum_label",
        "patients",
        "repeat_patients",
        "visits",
        "transitions",
        "known_age_patients",
        "median_age",
        "age_q1",
        "age_q3",
        "age_min",
        "age_max",
    ],
    "clinical_first_prescription_item_prevalence": [
        "group",
        "group_label",
        "components",
        "disease_count",
        "stratum_type",
        "stratum",
        "stratum_label",
        "item_name",
        "exposed_patients",
        "group_patients",
        "prevalence",
        "dose_patients",
        "most_common_dose_values_g",
        "most_common_dose_patients",
        "most_common_dose_fraction",
        "most_common_dose_tied",
    ],
    "clinical_frequent_item_combinations": [
        "group",
        "group_label",
        "components",
        "disease_count",
        "stratum_type",
        "stratum",
        "stratum_label",
        "patients",
        "combination_size",
        "combination",
        "support_patients",
        "support",
        "lift",
        "bootstrap_core_selection_probability",
        "stable_core_combination",
    ],
    "clinical_longitudinal_summary": [
        "group",
        "group_label",
        "components",
        "disease_count",
        "stratum_type",
        "stratum",
        "stratum_label",
        "repeat_patients",
        "transitions",
        "dose_resolved_patients",
        "dose_resolved_transitions",
        "median_patient_jaccard",
        "median_patient_retention",
        "median_patient_addition",
        "median_patient_modification_burden",
    ],
    "clinical_item_change_tendency": [
        "group",
        "group_label",
        "components",
        "disease_count",
        "stratum_type",
        "stratum",
        "stratum_label",
        "item_name",
        "change_type",
        "repeat_patients",
        "patients_with_change",
        "patient_prevalence",
        "mean_patient_transition_fraction",
        "dose_patients",
        "most_common_dose_values_g",
        "most_common_dose_patients",
        "most_common_dose_fraction",
        "most_common_dose_tied",
    ],
    "clinical_item_change_comparison": [
        "combination_group",
        "combination_label",
        "single_group",
        "single_label",
        "stratum_type",
        "stratum",
        "stratum_label",
        "change_type",
        "item_name",
        "combination_repeat_patients",
        "combination_patients_with_change",
        "combination_prevalence",
        "single_repeat_patients",
        "single_patients_with_change",
        "single_prevalence",
        "prevalence_difference",
        "combination_mean_transition_fraction",
        "single_mean_transition_fraction",
        "mean_transition_fraction_difference",
        "combination_dose_patients",
        "combination_most_common_dose_values_g",
        "combination_most_common_dose_patients",
        "combination_most_common_dose_fraction",
        "combination_most_common_dose_tied",
        "single_dose_patients",
        "single_most_common_dose_values_g",
        "single_most_common_dose_patients",
        "single_most_common_dose_fraction",
        "single_most_common_dose_tied",
        "higher_frequency",
    ],
    "clinical_year_summary": [
        "group",
        "group_label",
        "components",
        "disease_count",
        "stratum_type",
        "stratum",
        "stratum_label",
        "year",
        "patients",
        "repeat_patients",
        "visits",
        "transitions",
    ],
    "clinical_year_item_prevalence": [
        "group",
        "group_label",
        "components",
        "disease_count",
        "stratum_type",
        "stratum",
        "stratum_label",
        "year",
        "item_name",
        "exposed_patients",
        "group_patients",
        "prevalence",
        "dose_patients",
        "most_common_dose_values_g",
        "most_common_dose_patients",
        "most_common_dose_fraction",
        "most_common_dose_tied",
    ],
    "clinical_year_item_change_tendency": [
        "group",
        "group_label",
        "components",
        "disease_count",
        "stratum_type",
        "stratum",
        "stratum_label",
        "year",
        "item_name",
        "change_type",
        "repeat_patients",
        "patients_with_change",
        "patient_prevalence",
        "mean_patient_transition_fraction",
        "dose_patients",
        "most_common_dose_values_g",
        "most_common_dose_patients",
        "most_common_dose_fraction",
        "most_common_dose_tied",
    ],
}


@dataclass(frozen=True)
class ValidationContext:
    config_path: Path
    input_paths: tuple[Path, ...]
    config: AnalysisConfig
    read_result: ReadResult
    cohort_result: CohortResult
    visit_result: VisitBuildResult
    clinical_cohort_result: ClinicalPhenotypeCohortResult | None
    clinical_visit_result: VisitBuildResult | None
    gate: str
    warnings: tuple[str, ...]


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _normalize_input_paths(input_paths: Path | Sequence[Path]) -> tuple[Path, ...]:
    if isinstance(input_paths, Path):
        return (input_paths.resolve(),)
    return tuple(Path(path).resolve() for path in input_paths)


def validate_pipeline(
    config_path: Path, input_paths: Path | Sequence[Path]
) -> ValidationContext:
    config_path = config_path.resolve()
    resolved_input_paths = _normalize_input_paths(input_paths)
    config = load_config(config_path)
    repository_root = Path(__file__).resolve().parents[2]
    if not config.synthetic_mode:
        unsafe_paths = [
            path for path in resolved_input_paths if _is_within(path, repository_root)
        ]
        if unsafe_paths:
            raise InputError("Real clinical input must remain outside the Git repository")

    read_result = read_sources(resolved_input_paths, config)
    cohort_result = assign_patient_groups(read_result.records, config)
    if not cohort_result.patient_groups:
        raise InputError("No patients were assigned to exactly one configured group")
    visit_result = build_visits(read_result.records, cohort_result.patient_groups, config)
    if not visit_result.visits_by_patient:
        raise InputError("No analyzable visits remain after cohort assignment")

    clinical_cohort_result: ClinicalPhenotypeCohortResult | None = None
    clinical_visit_result: VisitBuildResult | None = None
    clinical_warnings: tuple[str, ...] = ()
    if config.clinical_phenotype_analysis.enabled:
        clinical_cohort_result = assign_clinical_phenotypes(read_result.records, config)
        if clinical_cohort_result.patient_groups:
            components = clinical_cohort_result.group_components
            clinical_visit_result = build_visits(
                read_result.records,
                clinical_cohort_result.patient_groups,
                config,
                visit_matcher=lambda group, text: matches_clinical_phenotype_visit(
                    text, components[group], config
                ),
            )
        clinical_warnings = clinical_cohort_result.warnings

    warnings = (
        *read_result.warnings,
        *cohort_result.warnings,
        *visit_result.warnings,
        *clinical_warnings,
    )
    return ValidationContext(
        config_path=config_path,
        input_paths=resolved_input_paths,
        config=config,
        read_result=read_result,
        cohort_result=cohort_result,
        visit_result=visit_result,
        clinical_cohort_result=clinical_cohort_result,
        clinical_visit_result=clinical_visit_result,
        gate="PASS_WITH_WARNINGS" if warnings else "PASS",
        warnings=warnings,
    )


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(
            {
                key: (f"{value:.9f}".rstrip("0").rstrip(".") if isinstance(value, float) else value)
                for key, value in row.items()
            }
            for row in rows
        )


def _format_value(value: object) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _markdown_table(rows: list[dict[str, object]], columns: list[str]) -> str:
    if not rows:
        return "No reportable rows."
    header = "| " + " | ".join(columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    body = [
        "| " + " | ".join(_format_value(row.get(column)) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def _top_combination_rows(
    rows: list[dict[str, object]], limit_per_group_size: int = 3
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    counts: dict[tuple[str, int], int] = {}
    for row in rows:
        key = (str(row["group"]), int(row["combination_size"]))
        if counts.get(key, 0) >= limit_per_group_size:
            continue
        selected.append(row)
        counts[key] = counts.get(key, 0) + 1
    return selected


def _top_item_change_rows(
    rows: list[dict[str, object]], limit_per_group_direction: int = 5
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row["group"]), str(row["change_type"]))
        if counts.get(key, 0) >= limit_per_group_direction:
            continue
        selected.append(row)
        counts[key] = counts.get(key, 0) + 1
    return selected


def _network_membership_summary_rows(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    counts: dict[tuple[str, str, str, int], int] = {}
    for row in rows:
        key = (
            str(row["member_type"]),
            str(row["groups_present"]),
            str(row["group_labels_present"]),
            int(row["groups_present_n"]),
        )
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "member_type": key[0],
            "groups_present": key[1],
            "group_labels_present": key[2],
            "groups_present_n": key[3],
            "members": count,
        }
        for key, count in sorted(
            counts.items(),
            key=lambda item: (
                0 if item[0][0] == "node" else 1,
                -item[0][3],
                item[0][1],
            ),
        )
    ]


def _top_clinical_comparison_rows(
    rows: list[dict[str, object]], limit_per_direction: int = 5
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    counts: dict[tuple[str, str, str, str], int] = {}
    for row in sorted(
        rows,
        key=lambda value: -abs(
            float(value["mean_transition_fraction_difference"])
        ),
    ):
        if row["stratum_type"] != "overall":
            continue
        key = (
            str(row["combination_group"]),
            str(row["single_group"]),
            str(row["change_type"]),
            str(row["higher_frequency"]),
        )
        if counts.get(key, 0) >= limit_per_direction:
            continue
        selected.append(row)
        counts[key] = counts.get(key, 0) + 1
    return selected


def _write_report(
    path: Path,
    context: ValidationContext,
    analysis: AnalysisResult,
    clinical_analysis: AnalysisResult,
) -> None:
    cohort_table = _markdown_table(
        analysis.tables["cohort_summary"], TABLE_FIELDS["cohort_summary"]
    )
    longitudinal_table = _markdown_table(
        analysis.tables["longitudinal_summary"], TABLE_FIELDS["longitudinal_summary"]
    )
    longitudinal_item_change_table = _markdown_table(
        _top_item_change_rows(
            analysis.tables["longitudinal_item_change_tendency"]
        ),
        TABLE_FIELDS["longitudinal_item_change_tendency"],
    )
    combination_table = _markdown_table(
        _top_combination_rows(analysis.tables["frequent_item_combinations"]),
        TABLE_FIELDS["frequent_item_combinations"],
    )
    network_table = _markdown_table(
        [
            row
            for row in analysis.tables["network_threshold_sensitivity"]
            if row["primary_setting"]
        ],
        [
            "group",
            "stable_nodes",
            "edges",
            "density",
            "connected_components",
            "largest_component_fraction",
        ],
    )
    network_overlap_table = _markdown_table(
        analysis.tables["network_group_overlap"],
        TABLE_FIELDS["network_group_overlap"],
    )
    network_membership_summary_table = _markdown_table(
        _network_membership_summary_rows(analysis.tables["network_membership"]),
        [
            "member_type",
            "groups_present",
            "group_labels_present",
            "groups_present_n",
            "members",
        ],
    )
    network_all_group_members_table = _markdown_table(
        [
            row
            for row in analysis.tables["network_membership"]
            if row["membership_class"] == "all_groups"
        ],
        ["member_type", "member", "group_labels_present"],
    )
    similarity_table = _markdown_table(
        analysis.tables["cross_group_similarity"], TABLE_FIELDS["cross_group_similarity"]
    )
    temporal_table = _markdown_table(
        analysis.tables["temporal_stability"], TABLE_FIELDS["temporal_stability"]
    )
    temporal_cutpoint_table = _markdown_table(
        analysis.tables["temporal_cutpoint_sensitivity"],
        TABLE_FIELDS["temporal_cutpoint_sensitivity"],
    )
    matched_table = _markdown_table(
        analysis.tables["matched_reference_summary"],
        TABLE_FIELDS["matched_reference_summary"],
    )
    matched_sensitivity_table = _markdown_table(
        analysis.tables["matched_reference_sensitivity"],
        TABLE_FIELDS["matched_reference_sensitivity"],
    )
    item_normalization_table = _markdown_table(
        analysis.tables["item_normalization_audit"],
        TABLE_FIELDS["item_normalization_audit"],
    )
    dose_conflict_table = _markdown_table(
        analysis.tables["dose_conflict_audit"],
        TABLE_FIELDS["dose_conflict_audit"],
    )
    clinical_section = ""
    if clinical_analysis.tables:
        clinical_summary = _markdown_table(
            [
                row
                for row in clinical_analysis.tables["clinical_phenotype_summary"]
                if row["stratum_type"] == "overall"
            ],
            [
                "group_label",
                "disease_count",
                "patients",
                "repeat_patients",
                "visits",
                "transitions",
                "median_age",
                "age_q1",
                "age_q3",
            ],
        )
        clinical_comparisons = _markdown_table(
            _top_clinical_comparison_rows(
                clinical_analysis.tables["clinical_item_change_comparison"]
            ),
            [
                "combination_label",
                "single_label",
                "change_type",
                "item_name",
                "combination_prevalence",
                "single_prevalence",
                "prevalence_difference",
                "combination_mean_transition_fraction",
                "single_mean_transition_fraction",
                "mean_transition_fraction_difference",
                "combination_dose_patients",
                "combination_most_common_dose_values_g",
                "combination_most_common_dose_patients",
                "single_dose_patients",
                "single_most_common_dose_values_g",
                "single_most_common_dose_patients",
                "higher_frequency",
            ],
        )
        clinical_years = _markdown_table(
            [
                row
                for row in clinical_analysis.tables["clinical_year_summary"]
                if row["stratum_type"] == "overall"
            ],
            [
                "group_label",
                "year",
                "patients",
                "repeat_patients",
                "visits",
                "transitions",
            ],
        )
        clinical_section = f"""
## Clinical comorbidity and demographic view

This secondary view uses exact target-disease signatures and does not alter the strict single-disease cohorts above. Age is calculated at the first eligible prescription. Sex and age strata are descriptive and unadjusted.

{clinical_summary}

### Combination-versus-single item-change differences

Only item directions that independently pass the public-patient threshold on both sides are shown. The primary ordering is the difference in mean patient-level transition fraction; patient prevalence is retained as context. Patient-equal most frequently recorded gram doses are independently suppressed unless both the usable patient total and highest-frequency exact-dose category meet the public minimum. Positive differences mean only higher recorded change frequency in the combination phenotype; they are not comorbidity effects or treatment rules.

{clinical_comparisons}

### Patient-year evolution coverage

Each patient contributes one annual index prescription. Adjacent changes are assigned to the year of the later visit and averaged after calculating patient-year transition fractions. Recorded gram doses are summarized under the same patient-year ordering with a separate disclosure gate. Suppressed cells are unavailable rather than zero.

{clinical_years}
"""
    report_warnings = dict.fromkeys(
        (
            *context.warnings,
            *analysis.warnings,
            *clinical_analysis.warnings,
        )
    )
    warning_lines = "\n".join(
        f"- {warning}"
        for warning in report_warnings
    ) or "- None"
    report = f"""# MingYiRx analysis report

**Gate:** `{context.gate if not analysis.warnings else 'PASS_WITH_WARNINGS'}`
**Project:** `{context.config.project_id}`
**Dataset:** `{context.config.dataset_id}`
**Cohort:** `{context.config.cohort_version}`

## Cohort flow

- Source patients: {context.cohort_result.total_patients}
- Assigned exclusive patients: {len(context.cohort_result.patient_groups)}
- Multiple-group patients excluded: {context.cohort_result.overlap_patients}
- Unmatched patients excluded: {context.cohort_result.unmatched_patients}

{cohort_table}

## Item normalization audit

{item_normalization_table}

## Dose conflict audit

{dose_conflict_table}

## Frequent first-prescription combinations

The table shows at most three combinations per group and size, including the prespecified stability classification. The complete privacy-screened aggregate table is available in `frequent_item_combinations.csv`.

{combination_table}

## Privacy-safe recurrent-item networks

Primary networks use stable recurrent items at the configured core-prevalence threshold and privacy-screened edges at the configured cosine threshold. Complete node, edge, threshold-grid, and cross-group membership results are provided in the network CSV files.

{network_table}

### Cross-group primary-network membership

Pairwise Jaccard compares membership in the thresholded public networks, not raw exposure. A missing member in another group means only that it did not pass all publication thresholds there.

{network_overlap_table}

{network_membership_summary_table}

Members retained in every configured group:

{network_all_group_members_table}

## Patient-linked adjacent-prescription change

{longitudinal_table}

### Reportable item-level addition and removal tendencies

Rows are patient-equal historical summaries. Each direction is shown only when at least the configured public minimum number of repeat patients experienced that change; a missing direction is not zero and is not a treatment recommendation. Repeated dose events first resolve to a unique within-patient mode, then the group-level most frequently recorded exact gram dose is reported only when its separate patient and exact-category disclosure gates pass; group ties are retained. The complete table is available in `longitudinal_item_change_tendency.csv`.

{longitudinal_item_change_table}

{clinical_section}

## Matched same-clinician different-patient reference

{matched_table}

## Matched-reference sensitivity analyses

{matched_sensitivity_table}

## Cross-group first-prescription similarity

{similarity_table}

## Patient-disjoint temporal stress test

{temporal_table}

## Temporal cut-point sensitivity

{temporal_cutpoint_table}

## Warnings

{warning_lines}

## Interpretation boundary

These results describe recorded prescription structure, historical gram-dose distributions, and follow-up modification in the supplied record system. Recorded doses are neither converted nor imputed and must not be interpreted as standard, optimal, recommended, or patient-specific doses. The results do not establish effectiveness, safety, prescribing appropriateness, mechanism, syndrome differentiation, diagnostic validity, or external transportability.
"""
    path.write_text(report, encoding="utf-8")


def _config_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_hashes(output_dir: Path, names: list[str]) -> dict[str, str]:
    return {name: file_sha256(output_dir / name) for name in names}


def run_pipeline(
    config_path: Path, input_paths: Path | Sequence[Path], output_dir: Path
) -> dict[str, object]:
    context = validate_pipeline(config_path, input_paths)
    analysis = analyze(context.visit_result, context.config)
    clinical_analysis = AnalysisResult(
        tables={},
        metadata={
            "enabled": context.config.clinical_phenotype_analysis.enabled
        },
        warnings=(),
    )
    if (
        context.clinical_cohort_result is not None
        and context.clinical_visit_result is not None
    ):
        clinical_analysis = analyze_clinical_phenotypes(
            context.clinical_visit_result,
            context.clinical_cohort_result,
            context.read_result.patient_demographics,
            context.config,
        )
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_files: list[str] = []
    for table_name, rows in {**analysis.tables, **clinical_analysis.tables}.items():
        filename = f"{table_name}.csv"
        _write_csv(output_dir / filename, TABLE_FIELDS[table_name], rows)
        generated_files.append(filename)
    _write_report(output_dir / "report.md", context, analysis, clinical_analysis)
    generated_files.append("report.md")

    privacy_scan: PrivacyScan = scan_public_outputs(output_dir)
    final_warnings = list(
        dict.fromkeys(
            (
                *context.warnings,
                *analysis.warnings,
                *clinical_analysis.warnings,
            )
        )
    )
    if privacy_scan.issues:
        final_warnings.extend(privacy_scan.issues)
    gate = "BLOCK" if privacy_scan.issues else (
        "PASS_WITH_WARNINGS" if final_warnings else "PASS"
    )

    manifest = {
        "gate": gate,
        "project_id": context.config.project_id,
        "dataset_id": context.config.dataset_id,
        "cohort_version": context.config.cohort_version,
        "mingyirx_version": __version__,
        "python_version": platform.python_version(),
        "inputs": [
            {
                "absolute_path": audit.absolute_path,
                "filename": audit.filename,
                "sha256": audit.sha256,
                "bytes": audit.bytes,
                "rows": audit.raw_rows,
                "column_count": audit.column_count,
                "schema_sha256": audit.schema_sha256,
                "duplicate_header_names": list(audit.duplicate_header_names),
                "access_mode": "read_only",
                "contains_sensitive_data": not context.config.synthetic_mode,
                "received_date": None,
                "source_immutability": (
                    "hash_locked"
                    if audit.filename.casefold()
                    in {
                        filename.casefold()
                        for filename in context.config.expected_input_sha256
                    }
                    else "hash_recorded_unlocked"
                ),
            }
            for audit in context.read_result.source_files
        ],
        "input_reconciliation": {
            "cross_file_overlap_policy": context.config.cross_file_overlap_policy,
            "raw_rows": context.read_result.row_count,
            "cross_file_overlap_rows_detected": (
                context.read_result.cross_file_overlap_rows_detected
            ),
            "cross_file_overlap_rows_removed": (
                context.read_result.cross_file_overlap_rows_removed
            ),
            "analysis_rows": context.read_result.analysis_row_count,
        },
        "configuration": {
            "absolute_path": str(context.config_path),
            "sha256": _config_sha256(context.config_path),
            "min_public_n": context.config.min_public_n,
            "synthetic_mode": context.config.synthetic_mode,
            "early_end_year": context.config.early_end_year,
            "temporal_cutpoints": list(context.config.temporal_cutpoints),
            "core_prevalence": context.config.core_prevalence,
            "item_normalization": {
                "version": context.config.item_normalization.version,
                "dictionary_path": (
                    str(context.config.item_normalization.dictionary_path)
                    if context.config.item_normalization.dictionary_path
                    else None
                ),
                "sha256": context.config.item_normalization.dictionary_sha256,
                "entries": len(context.config.item_normalization.mappings),
            },
            "matched_reference": {
                "enabled": context.config.matched_reference.enabled,
                "assume_single_physician": (
                    context.config.matched_reference.assume_single_physician
                ),
                "random_seed": context.config.matched_reference.random_seed,
                "bootstrap_replicates": (
                    context.config.matched_reference.bootstrap_replicates
                ),
                "null_replicates": context.config.matched_reference.null_replicates,
            },
            "combination_analysis": {
                "enabled": context.config.combination_analysis.enabled,
                "sizes": list(context.config.combination_analysis.sizes),
                "stability_probability": (
                    context.config.combination_analysis.stability_probability
                ),
            },
            "network_analysis": {
                "enabled": context.config.network_analysis.enabled,
                "primary_cosine": context.config.network_analysis.primary_cosine,
                "node_prevalence_thresholds": list(
                    context.config.network_analysis.node_prevalence_thresholds
                ),
                "edge_cosine_thresholds": list(
                    context.config.network_analysis.edge_cosine_thresholds
                ),
                "stability_probability": (
                    context.config.network_analysis.stability_probability
                ),
            },
            "clinical_phenotype_analysis": {
                "enabled": context.config.clinical_phenotype_analysis.enabled,
                "other_exclude_patterns": len(
                    context.config.clinical_phenotype_analysis.other_exclude_patterns
                ),
                "sex_categories": list(
                    context.config.clinical_phenotype_analysis.sex_labels
                ),
                "age_bands": [
                    {
                        "name": band.name,
                        "min_age": band.min_age,
                        "max_age": band.max_age,
                    }
                    for band in context.config.clinical_phenotype_analysis.age_bands
                ],
            },
        },
        "cohort_flow": {
            "source_patients": context.cohort_result.total_patients,
            "assigned_patients": len(context.cohort_result.patient_groups),
            "overlap_excluded": context.cohort_result.overlap_patients,
            "unmatched_excluded": context.cohort_result.unmatched_patients,
            "group_counts": context.cohort_result.group_counts,
        },
        "analysis": analysis.metadata,
        "clinical_phenotype_analysis": clinical_analysis.metadata,
        "demographic_quality": context.read_result.demographic_audit,
        "eligibility_flow": {
            "require_visit_group_match": context.config.require_visit_group_match,
            "group_mismatch_visits_excluded": (
                context.visit_result.group_mismatch_visit_count
            ),
            "eligible_item_lines": context.visit_result.eligible_item_line_count,
            "ineligible_item_lines_excluded": (
                context.visit_result.ineligible_item_line_count
            ),
            "visits_without_eligible_items_excluded": (
                context.visit_result.empty_eligible_visit_count
            ),
            "dictionary_matched_item_lines": (
                context.visit_result.dictionary_matched_item_line_count
            ),
            "changed_item_lines": context.visit_result.changed_item_line_count,
            "canonical_collision_visit_items": (
                context.visit_result.canonical_collision_visit_item_count
            ),
            "dose_conflict_visit_items": (
                context.visit_result.dose_conflict_item_count
            ),
        },
        "clinical_phenotype_eligibility_flow": (
            {
                "group_mismatch_visits_excluded": (
                    context.clinical_visit_result.group_mismatch_visit_count
                ),
                "eligible_item_lines": (
                    context.clinical_visit_result.eligible_item_line_count
                ),
                "ineligible_item_lines_excluded": (
                    context.clinical_visit_result.ineligible_item_line_count
                ),
                "visits_without_eligible_items_excluded": (
                    context.clinical_visit_result.empty_eligible_visit_count
                ),
            }
            if context.clinical_visit_result is not None
            else None
        ),
        "privacy_scan": {
            "files_scanned": privacy_scan.files_scanned,
            "issues": list(privacy_scan.issues),
        },
        "warnings": final_warnings,
        "artifacts": _artifact_hashes(output_dir, generated_files),
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if gate == "BLOCK":
        raise InputError("Generated artifacts failed the privacy scan; see run_manifest.json")
    return manifest
