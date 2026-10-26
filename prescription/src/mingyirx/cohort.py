from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .config import AnalysisConfig, GroupRule
from .io import LineRecord


@dataclass(frozen=True)
class CohortResult:
    patient_groups: dict[str, str]
    total_patients: int
    unmatched_patients: int
    overlap_patients: int
    group_counts: dict[str, int]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ClinicalPhenotypeCohortResult:
    patient_groups: dict[str, str]
    group_components: dict[str, tuple[str, ...]]
    group_labels: dict[str, str]
    group_counts: dict[str, int]
    target_patients: int
    other_disease_excluded_patients: int
    warnings: tuple[str, ...]


def matches_group(text: str, rule: GroupRule) -> bool:
    included = any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in rule.include_patterns)
    excluded = any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in rule.exclude_patterns)
    return included and not excluded


def _matches_target(text: str, rule: GroupRule) -> bool:
    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in rule.include_patterns
    )


def assign_clinical_phenotypes(
    records: tuple[LineRecord, ...], config: AnalysisConfig
) -> ClinicalPhenotypeCohortResult:
    clinical = config.clinical_phenotype_analysis
    if not clinical.enabled:
        return ClinicalPhenotypeCohortResult({}, {}, {}, {}, 0, 0, ())

    diagnosis_by_patient: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if record.diagnosis_text:
            diagnosis_by_patient[record.patient_id].add(record.diagnosis_text)
        else:
            diagnosis_by_patient.setdefault(record.patient_id, set())

    patient_groups: dict[str, str] = {}
    group_components: dict[str, tuple[str, ...]] = {}
    group_labels: dict[str, str] = {}
    group_counts: dict[str, int] = defaultdict(int)
    target_patients = 0
    other_disease_excluded_patients = 0
    labels = {group.name: group.label for group in config.groups}

    for patient_id, diagnosis_values in diagnosis_by_patient.items():
        full_history = " | ".join(sorted(diagnosis_values))
        components = tuple(
            group.name
            for group in config.groups
            if _matches_target(full_history, group)
        )
        if not components:
            continue
        target_patients += 1
        if any(
            re.search(pattern, full_history, flags=re.IGNORECASE)
            for pattern in clinical.other_exclude_patterns
        ):
            other_disease_excluded_patients += 1
            continue
        group_name = "__".join(components)
        patient_groups[patient_id] = group_name
        group_components[group_name] = components
        group_labels[group_name] = " + ".join(labels[component] for component in components)
        group_counts[group_name] += 1

    warnings: list[str] = []
    if any(count < config.min_public_n for count in group_counts.values()):
        warnings.append(
            "Some clinical phenotype groups are below min_public_n and remain suppressed"
        )
    return ClinicalPhenotypeCohortResult(
        patient_groups=patient_groups,
        group_components=group_components,
        group_labels=group_labels,
        group_counts=dict(group_counts),
        target_patients=target_patients,
        other_disease_excluded_patients=other_disease_excluded_patients,
        warnings=tuple(warnings),
    )


def matches_clinical_phenotype_visit(
    text: str,
    components: tuple[str, ...],
    config: AnalysisConfig,
) -> bool:
    rules = {group.name: group for group in config.groups}
    included = any(_matches_target(text, rules[component]) for component in components)
    excluded = any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in config.clinical_phenotype_analysis.other_exclude_patterns
    )
    return included and not excluded


def assign_patient_groups(records: tuple[LineRecord, ...], config: AnalysisConfig) -> CohortResult:
    diagnosis_by_patient: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if record.diagnosis_text:
            diagnosis_by_patient[record.patient_id].add(record.diagnosis_text)
        else:
            diagnosis_by_patient.setdefault(record.patient_id, set())

    patient_groups: dict[str, str] = {}
    overlap_patients = 0
    unmatched_patients = 0
    group_counts = {group.name: 0 for group in config.groups}

    for patient_id, diagnosis_values in diagnosis_by_patient.items():
        full_history = " | ".join(sorted(diagnosis_values))
        matches = [group.name for group in config.groups if matches_group(full_history, group)]
        if len(matches) == 1:
            patient_groups[patient_id] = matches[0]
            group_counts[matches[0]] += 1
        elif len(matches) > 1:
            overlap_patients += 1
        else:
            unmatched_patients += 1

    warnings: list[str] = []
    if overlap_patients:
        warnings.append(f"{overlap_patients} patients matched multiple configured groups and were excluded")
    if unmatched_patients:
        warnings.append(f"{unmatched_patients} patients matched no configured group and were excluded")
    for group_name, count in group_counts.items():
        if count < config.min_public_n:
            warnings.append(
                f"Group {group_name} is below min_public_n and requires suppression"
            )

    return CohortResult(
        patient_groups=patient_groups,
        total_patients=len(diagnosis_by_patient),
        unmatched_patients=unmatched_patients,
        overlap_patients=overlap_patients,
        group_counts=group_counts,
        warnings=tuple(warnings),
    )
