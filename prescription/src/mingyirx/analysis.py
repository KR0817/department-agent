from __future__ import annotations

import itertools
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Callable

from .config import AnalysisConfig
from .cohort import ClinicalPhenotypeCohortResult, matches_group
from .io import InputError, LineRecord, PatientDemographics, normalize_text


DoseValue = tuple[float, str] | None
TRANSITION_MODES = (
    "exact_repeat",
    "dose_only",
    "composition_only",
    "composition_and_dose",
)


@dataclass(frozen=True)
class PrescriptionVisit:
    patient_id: str
    group: str
    visit_id: str
    visit_date: date
    physician_id: str
    items: frozenset[str]
    doses: dict[str, DoseValue]
    dose_resolved: bool


@dataclass(frozen=True)
class TransitionMetrics:
    jaccard: float
    retention: float
    addition: float
    modification_burden: float | None
    mode: str
    added_n: int
    removed_n: int
    dose_changed_n: int


@dataclass(frozen=True)
class VisitBuildResult:
    visits_by_patient: dict[str, tuple[PrescriptionVisit, ...]]
    dose_conflict_item_count: int
    dose_conflict_patients_by_group: dict[str, int]
    dose_conflict_visits_by_group: dict[str, int]
    dose_conflict_items_by_group: dict[str, int]
    eligible_item_line_count: int
    ineligible_item_line_count: int
    group_mismatch_visit_count: int
    empty_eligible_visit_count: int
    dictionary_matched_item_line_count: int
    changed_item_line_count: int
    distinct_source_item_count: int
    dictionary_matched_source_item_count: int
    canonical_item_count: int
    canonical_collision_visit_item_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class AnalysisResult:
    tables: dict[str, list[dict[str, object]]]
    metadata: dict[str, object]
    warnings: tuple[str, ...]


def build_visits(
    records: tuple[LineRecord, ...],
    patient_groups: dict[str, str],
    config: AnalysisConfig,
    visit_matcher: Callable[[str, str], bool] | None = None,
) -> VisitBuildResult:
    visit_lines: dict[tuple[str, str], list[LineRecord]] = defaultdict(list)
    for record in records:
        if record.patient_id in patient_groups:
            visit_lines[(record.patient_id, record.visit_id)].append(record)

    visits_by_patient: dict[str, list[PrescriptionVisit]] = defaultdict(list)
    dose_conflict_item_count = 0
    dose_conflict_patients: dict[str, set[str]] = defaultdict(set)
    dose_conflict_visits_by_group = Counter()
    dose_conflict_items_by_group = Counter()
    eligible_item_line_count = 0
    ineligible_item_line_count = 0
    group_mismatch_visit_count = 0
    empty_eligible_visit_count = 0
    dictionary_matched_item_line_count = 0
    changed_item_line_count = 0
    eligible_source_items: set[str] = set()
    dictionary_matched_source_items: set[str] = set()
    canonical_items: set[str] = set()
    canonical_collision_visit_item_count = 0
    item_mappings = config.item_normalization.mappings
    group_rules = {group.name: group for group in config.groups}
    allowed_units = {
        normalize_text(unit).casefold() for unit in config.item_eligibility.allowed_units
    }
    excluded_exact_names = {
        normalize_text(name).casefold()
        for name in config.item_eligibility.excluded_exact_names
    }
    excluded_patterns = tuple(
        re.compile(pattern, flags=re.IGNORECASE)
        for pattern in config.item_eligibility.excluded_name_patterns
    )

    for (patient_id, visit_id), lines in visit_lines.items():
        dates = {line.visit_date for line in lines}
        if len(dates) != 1:
            raise InputError("One visit for one patient has conflicting dates")
        group_name = patient_groups[patient_id]
        physician_ids = {line.physician_id for line in lines if line.physician_id}
        if len(physician_ids) > 1:
            raise InputError("One visit has conflicting physician identifiers")
        if config.require_visit_group_match:
            diagnosis_text = " | ".join(
                sorted({line.diagnosis_text for line in lines if line.diagnosis_text})
            )
            visit_matches = (
                visit_matcher(group_name, diagnosis_text)
                if visit_matcher is not None
                else matches_group(diagnosis_text, group_rules[group_name])
            )
            if not visit_matches:
                group_mismatch_visit_count += 1
                continue

        eligible_lines: list[LineRecord] = []
        for line in lines:
            unit_allowed = not allowed_units or line.unit.casefold() in allowed_units
            exact_excluded = line.item_name.casefold() in excluded_exact_names
            pattern_excluded = any(
                pattern.search(line.item_name) for pattern in excluded_patterns
            )
            if unit_allowed and not exact_excluded and not pattern_excluded:
                eligible_lines.append(line)
            else:
                ineligible_item_line_count += 1
        eligible_item_line_count += len(eligible_lines)
        if not eligible_lines:
            empty_eligible_visit_count += 1
            continue

        dose_values: dict[str, set[tuple[float, str]]] = defaultdict(set)
        source_names_by_item: dict[str, set[str]] = defaultdict(set)
        for line in eligible_lines:
            source_item = line.item_name
            canonical_item = item_mappings.get(source_item, source_item)
            eligible_source_items.add(source_item)
            canonical_items.add(canonical_item)
            source_names_by_item[canonical_item].add(source_item)
            if source_item in item_mappings:
                dictionary_matched_item_line_count += 1
                dictionary_matched_source_items.add(source_item)
                if canonical_item != source_item:
                    changed_item_line_count += 1
            if line.dose is not None:
                dose_values[canonical_item].add((line.dose, line.unit))

        items = set(source_names_by_item)
        canonical_collision_visit_item_count += sum(
            len(source_names) > 1 for source_names in source_names_by_item.values()
        )

        resolved_doses: dict[str, DoseValue] = {}
        visit_conflict_item_count = 0
        for item in items:
            values = dose_values.get(item, set())
            if len(values) == 1:
                resolved_doses[item] = next(iter(values))
            else:
                resolved_doses[item] = None
                if len(values) > 1:
                    dose_conflict_item_count += 1
                    visit_conflict_item_count += 1

        if visit_conflict_item_count:
            dose_conflict_patients[group_name].add(patient_id)
            dose_conflict_visits_by_group[group_name] += 1
            dose_conflict_items_by_group[group_name] += visit_conflict_item_count

        visits_by_patient[patient_id].append(
            PrescriptionVisit(
                patient_id=patient_id,
                group=group_name,
                visit_id=visit_id,
                visit_date=next(iter(dates)),
                physician_id=next(iter(physician_ids), ""),
                items=frozenset(items),
                doses=resolved_doses,
                dose_resolved=all(
                    resolved_doses[item] is not None for item in items
                ),
            )
        )

    ordered: dict[str, tuple[PrescriptionVisit, ...]] = {}
    for patient_id, visits in visits_by_patient.items():
        ordered[patient_id] = tuple(sorted(visits, key=lambda visit: (visit.visit_date, visit.visit_id)))

    warnings: list[str] = []
    if dose_conflict_item_count:
        warnings.append(
            "Dose conflicts were found; see the aggregate dose-conflict audit"
        )
    if group_mismatch_visit_count:
        warnings.append(
            f"{group_mismatch_visit_count} visits did not match the assigned recorded-label group"
        )
    if ineligible_item_line_count:
        warnings.append(
            f"{ineligible_item_line_count} medication item lines were excluded by item eligibility rules"
        )
    if empty_eligible_visit_count:
        warnings.append(
            f"{empty_eligible_visit_count} visits contained no eligible medication items"
        )
    if config.item_normalization.dictionary_path is None:
        warnings.append(
            "No item dictionary was applied; normalized source strings were preserved"
        )
    elif len(dictionary_matched_source_items) < len(eligible_source_items):
        warnings.append(
            "Some eligible source item names were not present in the item dictionary "
            "and were preserved"
        )
    return VisitBuildResult(
        visits_by_patient=ordered,
        dose_conflict_item_count=dose_conflict_item_count,
        dose_conflict_patients_by_group={
            group: len(patients) for group, patients in dose_conflict_patients.items()
        },
        dose_conflict_visits_by_group=dict(dose_conflict_visits_by_group),
        dose_conflict_items_by_group=dict(dose_conflict_items_by_group),
        eligible_item_line_count=eligible_item_line_count,
        ineligible_item_line_count=ineligible_item_line_count,
        group_mismatch_visit_count=group_mismatch_visit_count,
        empty_eligible_visit_count=empty_eligible_visit_count,
        dictionary_matched_item_line_count=dictionary_matched_item_line_count,
        changed_item_line_count=changed_item_line_count,
        distinct_source_item_count=len(eligible_source_items),
        dictionary_matched_source_item_count=len(dictionary_matched_source_items),
        canonical_item_count=len(canonical_items),
        canonical_collision_visit_item_count=canonical_collision_visit_item_count,
        warnings=tuple(warnings),
    )


def transition_metrics(previous: PrescriptionVisit, current: PrescriptionVisit) -> TransitionMetrics:
    union = previous.items | current.items
    intersection = previous.items & current.items
    added = current.items - previous.items
    removed = previous.items - current.items
    if not union:
        raise ValueError("Prescription visits cannot have empty item sets")

    dose_changed_n = 0
    dose_resolved = previous.dose_resolved and current.dose_resolved
    if dose_resolved:
        for item in intersection:
            previous_dose = previous.doses[item]
            current_dose = current.doses[item]
            if previous_dose is None or current_dose is None:
                raise ValueError("Resolved visits must have a dose for every item")
            previous_value, previous_unit = previous_dose
            current_value, current_unit = current_dose
            if previous_unit != current_unit:
                dose_resolved = False
                break
            if not math.isclose(
                previous_value, current_value, rel_tol=1e-12, abs_tol=1e-12
            ):
                dose_changed_n += 1

    composition_changed = bool(added or removed)
    if not dose_resolved:
        mode = "dose_unresolved"
    elif composition_changed and dose_changed_n:
        mode = "composition_and_dose"
    elif composition_changed:
        mode = "composition_only"
    elif dose_changed_n:
        mode = "dose_only"
    else:
        mode = "exact_repeat"

    return TransitionMetrics(
        jaccard=len(intersection) / len(union),
        retention=len(intersection) / len(previous.items),
        addition=len(added) / len(current.items),
        modification_burden=(
            (len(added) + len(removed) + dose_changed_n) / len(union)
            if dose_resolved
            else None
        ),
        mode=mode,
        added_n=len(added),
        removed_n=len(removed),
        dose_changed_n=dose_changed_n,
    )


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _gram_dose(visit: PrescriptionVisit, item: str) -> float | None:
    """Return an explicitly recorded gram dose without converting units."""
    dose = visit.doses.get(item)
    if dose is None:
        return None
    value, unit = dose
    return value if unit.casefold() == "g" else None


def _unique_mode(values: list[float]) -> float | None:
    """Return one modal value, leaving tied personal histories unresolved."""
    if not values:
        return None
    counts = Counter(values)
    maximum = max(counts.values())
    modes = [value for value, count in counts.items() if count == maximum]
    return modes[0] if len(modes) == 1 else None


def _dose_mode_summary(
    values: list[float], min_public_n: int
) -> dict[str, int | float | str | bool | None]:
    """Return privacy-gated patient-level gram-dose modes."""
    empty: dict[str, int | float | str | bool | None] = {
        "dose_patients": None,
        "most_common_dose_values_g": None,
        "most_common_dose_patients": None,
        "most_common_dose_fraction": None,
        "most_common_dose_tied": None,
    }
    if len(values) < min_public_n:
        return empty
    counts = Counter(values)
    maximum = max(counts.values())
    if maximum < min_public_n:
        return empty
    modes = sorted(value for value, count in counts.items() if count == maximum)
    return {
        "dose_patients": len(values),
        "most_common_dose_values_g": ";".join(
            format(value, ".9g") for value in modes
        ),
        "most_common_dose_patients": maximum,
        "most_common_dose_fraction": maximum / len(values),
        "most_common_dose_tied": len(modes) > 1,
    }


def _weighted_jaccard(left: dict[str, float], right: dict[str, float], items: set[str]) -> float | None:
    if not items:
        return None
    denominator = sum(max(left.get(item, 0.0), right.get(item, 0.0)) for item in items)
    if denominator == 0:
        return None
    numerator = sum(min(left.get(item, 0.0), right.get(item, 0.0)) for item in items)
    return numerator / denominator


def _jensen_shannon_distance(
    left: dict[str, float], right: dict[str, float], items: set[str]
) -> float | None:
    if not items:
        return None
    left_values = [left.get(item, 0.0) for item in sorted(items)]
    right_values = [right.get(item, 0.0) for item in sorted(items)]
    left_total = sum(left_values)
    right_total = sum(right_values)
    if left_total == 0 or right_total == 0:
        return None
    p = [value / left_total for value in left_values]
    q = [value / right_total for value in right_values]
    m = [(p_value + q_value) / 2 for p_value, q_value in zip(p, q, strict=True)]

    def kl(values: list[float], midpoint: list[float]) -> float:
        return sum(
            value * math.log2(value / middle)
            for value, middle in zip(values, midpoint, strict=True)
            if value
        )

    return math.sqrt((kl(p, m) + kl(q, m)) / 2)


def _first_visits(
    visits_by_patient: dict[str, tuple[PrescriptionVisit, ...]],
) -> dict[str, PrescriptionVisit]:
    return {patient_id: visits[0] for patient_id, visits in visits_by_patient.items() if visits}


def _binomial_survival_probability(
    sample_size: int, probability: float, minimum_count: int
) -> float:
    """Return P[X >= minimum_count] for X ~ Binomial(sample_size, probability)."""
    if minimum_count <= 0:
        return 1.0
    if minimum_count > sample_size or probability <= 0:
        return 0.0
    if probability >= 1:
        return 1.0

    log_probability = math.log(probability)
    log_complement = math.log1p(-probability)

    def probability_mass(count: int) -> float:
        return math.exp(
            math.lgamma(sample_size + 1)
            - math.lgamma(count + 1)
            - math.lgamma(sample_size - count + 1)
            + count * log_probability
            + (sample_size - count) * log_complement
        )

    mode = math.floor((sample_size + 1) * probability)
    if minimum_count <= mode:
        count = minimum_count - 1
        mass = probability_mass(count)
        lower_tail = mass
        while count > 0:
            mass *= count / (sample_size - count + 1)
            mass *= (1 - probability) / probability
            lower_tail += mass
            count -= 1
        result = 1 - lower_tail
    else:
        count = minimum_count
        mass = probability_mass(count)
        result = mass
        while count < sample_size:
            mass *= (sample_size - count) / (count + 1)
            mass *= probability / (1 - probability)
            result += mass
            count += 1
    return max(0.0, min(1.0, result))


def _frequent_combination_rows(
    first_visits: dict[str, PrescriptionVisit],
    config: AnalysisConfig,
    group_names: tuple[str, ...] | None = None,
) -> tuple[list[dict[str, object]], dict[str, object], tuple[str, ...]]:
    combination_config = config.combination_analysis
    metadata: dict[str, object] = {
        "enabled": combination_config.enabled,
        "sizes": list(combination_config.sizes),
        "minimum_support_patients": config.min_public_n,
        "minimum_support": config.core_prevalence,
        "stability_probability_threshold": (
            combination_config.stability_probability
        ),
        "candidate_combinations": 0,
        "stable_combinations": 0,
    }
    if not combination_config.enabled:
        return [], metadata, ()

    selected_groups = group_names or tuple(group.name for group in config.groups)
    group_order = {group: index for index, group in enumerate(selected_groups)}
    group_visits: dict[str, list[PrescriptionVisit]] = {
        group: [] for group in selected_groups
    }
    for visit in first_visits.values():
        group_visits[visit.group].append(visit)

    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    for group in group_order:
        visits = group_visits[group]
        patient_count = len(visits)
        if patient_count < config.min_public_n:
            warnings.append(
                f"Combination analysis for {group} was suppressed because the public threshold was not met"
            )
            continue

        item_counts: Counter[str] = Counter()
        for visit in visits:
            item_counts.update(visit.items)
        public_items = {
            item for item, count in item_counts.items() if count >= config.min_public_n
        }

        for size in combination_config.sizes:
            combination_counts: Counter[tuple[str, ...]] = Counter()
            for visit in visits:
                eligible_items = sorted(visit.items & public_items)
                combination_counts.update(itertools.combinations(eligible_items, size))

            minimum_core_count = math.ceil(
                patient_count * config.core_prevalence
            )
            for combination, support_patients in combination_counts.items():
                support = support_patients / patient_count
                if (
                    support_patients < config.min_public_n
                    or support < config.core_prevalence
                ):
                    continue
                expected_support = math.prod(
                    item_counts[item] / patient_count for item in combination
                )
                selection_probability = _binomial_survival_probability(
                    patient_count, support, minimum_core_count
                )
                rows.append(
                    {
                        "group": group,
                        "patients": patient_count,
                        "combination_size": size,
                        "combination": " | ".join(combination),
                        "support_patients": support_patients,
                        "support": support,
                        "lift": support / expected_support,
                        "bootstrap_core_selection_probability": selection_probability,
                        "stable_core_combination": (
                            selection_probability
                            >= combination_config.stability_probability
                        ),
                    }
                )

    rows.sort(
        key=lambda row: (
            group_order[str(row["group"])],
            int(row["combination_size"]),
            -float(row["support"]),
            -float(row["lift"]),
            str(row["combination"]),
        )
    )
    metadata["candidate_combinations"] = len(rows)
    metadata["stable_combinations"] = sum(
        bool(row["stable_core_combination"]) for row in rows
    )
    return rows, metadata, tuple(warnings)


def _network_components(
    nodes: set[str], edges: set[tuple[str, str]]
) -> list[set[str]]:
    adjacency = {node: set() for node in nodes}
    for left, right in edges:
        adjacency[left].add(right)
        adjacency[right].add(left)

    components: list[set[str]] = []
    remaining = set(nodes)
    while remaining:
        seed = min(remaining)
        component: set[str] = set()
        pending = [seed]
        while pending:
            node = pending.pop()
            if node in component:
                continue
            component.add(node)
            pending.extend(adjacency[node] - component)
        remaining -= component
        components.append(component)
    return components


def _membership_comparison(
    current: set[object], primary: set[object]
) -> tuple[float | None, float | None]:
    if not primary:
        return None, None
    intersection = len(current & primary)
    union = len(current | primary)
    return intersection / len(primary), intersection / union


def _network_cross_group_rows(
    group_names: tuple[str, ...],
    group_labels: dict[str, str],
    nodes_by_group: dict[str, set[str]],
    edges_by_group: dict[str, set[tuple[str, str]]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    overlap_rows: list[dict[str, object]] = []
    for left, right in itertools.combinations(group_names, 2):
        left_nodes = nodes_by_group[left]
        right_nodes = nodes_by_group[right]
        node_union = left_nodes | right_nodes
        left_edges = edges_by_group[left]
        right_edges = edges_by_group[right]
        edge_union = left_edges | right_edges
        overlap_rows.append(
            {
                "group_left": left,
                "group_left_label": group_labels[left],
                "group_right": right,
                "group_right_label": group_labels[right],
                "left_nodes": len(left_nodes),
                "right_nodes": len(right_nodes),
                "common_nodes": len(left_nodes & right_nodes),
                "node_jaccard": (
                    len(left_nodes & right_nodes) / len(node_union)
                    if node_union
                    else None
                ),
                "left_edges": len(left_edges),
                "right_edges": len(right_edges),
                "common_edges": len(left_edges & right_edges),
                "edge_jaccard": (
                    len(left_edges & right_edges) / len(edge_union)
                    if edge_union
                    else None
                ),
            }
        )

    membership_rows: list[dict[str, object]] = []
    all_nodes = set().union(*(nodes_by_group[group] for group in group_names))
    all_edges = set().union(*(edges_by_group[group] for group in group_names))
    total_groups = len(group_names)

    def add_membership(
        member_type: str, member: str, item_1: str, item_2: str | None
    ) -> None:
        memberships = nodes_by_group if member_type == "node" else edges_by_group
        key: object = item_1 if member_type == "node" else (item_1, item_2)
        present = tuple(group for group in group_names if key in memberships[group])
        present_n = len(present)
        if present_n == total_groups:
            membership_class = "all_groups"
        elif present_n == 1:
            membership_class = "single_group"
        else:
            membership_class = "multi_group"
        membership_rows.append(
            {
                "member_type": member_type,
                "member": member,
                "item_1": item_1,
                "item_2": item_2,
                "groups_present": ";".join(present),
                "group_labels_present": ";".join(
                    group_labels[group] for group in present
                ),
                "groups_present_n": present_n,
                "membership_class": membership_class,
            }
        )

    for item in sorted(all_nodes):
        add_membership("node", item, item, None)
    for left, right in sorted(all_edges):
        add_membership("edge", f"{left} | {right}", left, right)
    membership_rows.sort(
        key=lambda row: (
            0 if row["member_type"] == "node" else 1,
            -int(row["groups_present_n"]),
            str(row["groups_present"]),
            str(row["member"]),
        )
    )
    return overlap_rows, membership_rows


def _network_setting(
    patient_count: int,
    item_counts: Counter[str],
    pair_counts: Counter[tuple[str, str]],
    node_threshold: float,
    cosine_threshold: float,
    min_public_n: int,
    stability_probability: float,
) -> tuple[dict[str, float], dict[tuple[str, str], dict[str, float | int]]]:
    minimum_node_count = math.ceil(patient_count * node_threshold)
    nodes: dict[str, float] = {}
    for item, exposed_patients in item_counts.items():
        prevalence = exposed_patients / patient_count
        if exposed_patients < min_public_n or prevalence < node_threshold:
            continue
        selection_probability = _binomial_survival_probability(
            patient_count, prevalence, minimum_node_count
        )
        if selection_probability >= stability_probability:
            nodes[item] = selection_probability

    edges: dict[tuple[str, str], dict[str, float | int]] = {}
    for (left, right), cooccurrence_patients in pair_counts.items():
        if (
            left not in nodes
            or right not in nodes
            or cooccurrence_patients < min_public_n
        ):
            continue
        cosine = cooccurrence_patients / math.sqrt(
            item_counts[left] * item_counts[right]
        )
        if cosine < cosine_threshold:
            continue
        support = cooccurrence_patients / patient_count
        expected_support = (
            item_counts[left] / patient_count
        ) * (item_counts[right] / patient_count)
        edges[(left, right)] = {
            "cooccurrence_patients": cooccurrence_patients,
            "support": support,
            "cosine_similarity": cosine,
            "lift": support / expected_support,
        }
    return nodes, edges


def _network_rows(
    first_visits: dict[str, PrescriptionVisit], config: AnalysisConfig
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
    tuple[str, ...],
]:
    network_config = config.network_analysis
    metadata: dict[str, object] = {
        "enabled": network_config.enabled,
        "primary_node_prevalence": config.core_prevalence,
        "primary_edge_cosine": network_config.primary_cosine,
        "stability_probability_threshold": network_config.stability_probability,
        "node_prevalence_thresholds": list(
            network_config.node_prevalence_thresholds
        ),
        "edge_cosine_thresholds": list(network_config.edge_cosine_thresholds),
        "primary_nodes": 0,
        "primary_edges": 0,
        "sensitivity_rows": 0,
        "group_overlap_rows": 0,
        "membership_rows": 0,
    }
    if not network_config.enabled:
        return [], [], [], [], [], metadata, ()

    group_order = {
        group.name: index for index, group in enumerate(config.groups)
    }
    group_labels = {group.name: group.label for group in config.groups}
    visits_by_group: dict[str, list[PrescriptionVisit]] = {
        group.name: [] for group in config.groups
    }
    for visit in first_visits.values():
        visits_by_group[visit.group].append(visit)

    node_rows: list[dict[str, object]] = []
    edge_rows: list[dict[str, object]] = []
    sensitivity_rows: list[dict[str, object]] = []
    primary_nodes_by_group: dict[str, set[str]] = {
        group: set() for group in group_order
    }
    primary_edges_by_group: dict[str, set[tuple[str, str]]] = {
        group: set() for group in group_order
    }
    warnings: list[str] = []

    for group in group_order:
        visits = visits_by_group[group]
        patient_count = len(visits)
        if patient_count < config.min_public_n:
            warnings.append(
                f"Network analysis for {group} was suppressed because the public threshold was not met"
            )
            continue

        item_counts: Counter[str] = Counter()
        for visit in visits:
            item_counts.update(visit.items)
        public_items = {
            item for item, count in item_counts.items() if count >= config.min_public_n
        }
        pair_counts: Counter[tuple[str, str]] = Counter()
        for visit in visits:
            pair_counts.update(
                itertools.combinations(sorted(visit.items & public_items), 2)
            )

        settings: dict[
            tuple[float, float],
            tuple[dict[str, float], dict[tuple[str, str], dict[str, float | int]]],
        ] = {}
        for node_threshold in network_config.node_prevalence_thresholds:
            for cosine_threshold in network_config.edge_cosine_thresholds:
                settings[(node_threshold, cosine_threshold)] = _network_setting(
                    patient_count,
                    item_counts,
                    pair_counts,
                    node_threshold,
                    cosine_threshold,
                    config.min_public_n,
                    network_config.stability_probability,
                )

        primary_nodes, primary_edges = settings[
            (config.core_prevalence, network_config.primary_cosine)
        ]
        primary_node_set = set(primary_nodes)
        primary_edge_set = set(primary_edges)
        primary_nodes_by_group[group] = primary_node_set
        primary_edges_by_group[group] = primary_edge_set

        degrees = {node: 0 for node in primary_nodes}
        weighted_degrees = {node: 0.0 for node in primary_nodes}
        for (left, right), attributes in primary_edges.items():
            cosine = float(attributes["cosine_similarity"])
            degrees[left] += 1
            degrees[right] += 1
            weighted_degrees[left] += cosine
            weighted_degrees[right] += cosine

        for item, selection_probability in primary_nodes.items():
            node_rows.append(
                {
                    "group": group,
                    "group_label": group_labels[group],
                    "patients": patient_count,
                    "node_prevalence_threshold": config.core_prevalence,
                    "edge_cosine_threshold": network_config.primary_cosine,
                    "item_name": item,
                    "exposed_patients": item_counts[item],
                    "prevalence": item_counts[item] / patient_count,
                    "bootstrap_core_selection_probability": selection_probability,
                    "degree": degrees[item],
                    "weighted_degree": weighted_degrees[item],
                }
            )

        for (left, right), attributes in primary_edges.items():
            edge_rows.append(
                {
                    "group": group,
                    "group_label": group_labels[group],
                    "patients": patient_count,
                    "node_prevalence_threshold": config.core_prevalence,
                    "edge_cosine_threshold": network_config.primary_cosine,
                    "item_1": left,
                    "item_2": right,
                    **attributes,
                }
            )

        for (node_threshold, cosine_threshold), (nodes, edges) in settings.items():
            node_set = set(nodes)
            edge_set = set(edges)
            components = _network_components(node_set, edge_set)
            node_retention, node_jaccard = _membership_comparison(
                node_set, primary_node_set
            )
            edge_retention, edge_jaccard = _membership_comparison(
                edge_set, primary_edge_set
            )
            possible_edges = len(node_set) * (len(node_set) - 1) / 2
            sensitivity_rows.append(
                {
                    "group": group,
                    "group_label": group_labels[group],
                    "patients": patient_count,
                    "node_prevalence_threshold": node_threshold,
                    "edge_cosine_threshold": cosine_threshold,
                    "stable_nodes": len(node_set),
                    "edges": len(edge_set),
                    "density": len(edge_set) / possible_edges if possible_edges else 0.0,
                    "connected_components": len(components),
                    "largest_component_fraction": (
                        max(map(len, components)) / len(node_set)
                        if components
                        else 0.0
                    ),
                    "node_retention_vs_primary": node_retention,
                    "node_jaccard_vs_primary": node_jaccard,
                    "edge_retention_vs_primary": edge_retention,
                    "edge_jaccard_vs_primary": edge_jaccard,
                    "primary_setting": (
                        node_threshold == config.core_prevalence
                        and cosine_threshold == network_config.primary_cosine
                    ),
                }
            )

    node_rows.sort(
        key=lambda row: (
            group_order[str(row["group"])],
            -float(row["prevalence"]),
            str(row["item_name"]),
        )
    )
    edge_rows.sort(
        key=lambda row: (
            group_order[str(row["group"])],
            -float(row["cosine_similarity"]),
            -float(row["support"]),
            str(row["item_1"]),
            str(row["item_2"]),
        )
    )
    sensitivity_rows.sort(
        key=lambda row: (
            group_order[str(row["group"])],
            float(row["node_prevalence_threshold"]),
            float(row["edge_cosine_threshold"]),
        )
    )
    overlap_rows, membership_rows = _network_cross_group_rows(
        tuple(group_order),
        group_labels,
        primary_nodes_by_group,
        primary_edges_by_group,
    )
    metadata["primary_nodes"] = len(node_rows)
    metadata["primary_edges"] = len(edge_rows)
    metadata["sensitivity_rows"] = len(sensitivity_rows)
    metadata["group_overlap_rows"] = len(overlap_rows)
    metadata["membership_rows"] = len(membership_rows)
    return (
        node_rows,
        edge_rows,
        sensitivity_rows,
        overlap_rows,
        membership_rows,
        metadata,
        tuple(warnings),
    )


def _prevalence(
    first_visits: dict[str, PrescriptionVisit], group_names: tuple[str, ...]
) -> tuple[dict[str, Counter[str]], dict[str, dict[str, float]], dict[str, int]]:
    counts = {group: Counter() for group in group_names}
    denominators = {group: 0 for group in group_names}
    for visit in first_visits.values():
        denominators[visit.group] += 1
        counts[visit.group].update(visit.items)
    prevalence = {
        group: {
            item: count / denominators[group]
            for item, count in group_counts.items()
            if denominators[group]
        }
        for group, group_counts in counts.items()
    }
    return counts, prevalence, denominators


def _cohort_summary(
    visits_by_patient: dict[str, tuple[PrescriptionVisit, ...]], group_names: tuple[str, ...]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for group in group_names:
        group_visits = [visits for visits in visits_by_patient.values() if visits and visits[0].group == group]
        rows.append(
            {
                "group": group,
                "patients": len(group_visits),
                "first_prescription_patients": len(group_visits),
                "repeat_patients": sum(len(visits) >= 2 for visits in group_visits),
                "visits": sum(len(visits) for visits in group_visits),
                "transitions": sum(max(0, len(visits) - 1) for visits in group_visits),
            }
        )
    return rows


def _first_prescription_rows(
    counts: dict[str, Counter[str]],
    prevalence: dict[str, dict[str, float]],
    denominators: dict[str, int],
    first_visits: dict[str, PrescriptionVisit],
    min_public_n: int,
) -> tuple[list[dict[str, object]], int]:
    doses_by_group_item: dict[tuple[str, str], list[float]] = defaultdict(list)
    for visit in first_visits.values():
        for item in visit.items:
            dose = _gram_dose(visit, item)
            if dose is not None:
                doses_by_group_item[(visit.group, item)].append(dose)

    rows: list[dict[str, object]] = []
    suppressed = 0
    for group, item_counts in counts.items():
        for item, count in sorted(item_counts.items(), key=lambda pair: (-pair[1], pair[0])):
            if count < min_public_n:
                suppressed += 1
                continue
            rows.append(
                {
                    "group": group,
                    "item_name": item,
                    "exposed_patients": count,
                    "group_patients": denominators[group],
                    "prevalence": prevalence[group][item],
                    **_dose_mode_summary(
                        doses_by_group_item[(group, item)], min_public_n
                    ),
                }
            )
    return rows, suppressed


def _longitudinal_rows(
    visits_by_patient: dict[str, tuple[PrescriptionVisit, ...]], group_names: tuple[str, ...]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    patient_summaries: dict[str, list[dict[str, object]]] = {group: [] for group in group_names}
    for visits in visits_by_patient.values():
        if len(visits) < 2:
            continue
        transitions = [transition_metrics(left, right) for left, right in itertools.pairwise(visits)]
        dose_resolved = [
            metric for metric in transitions if metric.modification_burden is not None
        ]
        mode_counts = Counter(metric.mode for metric in dose_resolved)
        patient_summaries[visits[0].group].append(
            {
                "transition_n": len(transitions),
                "dose_transition_n": len(dose_resolved),
                "jaccard": statistics.median(metric.jaccard for metric in transitions),
                "retention": statistics.median(metric.retention for metric in transitions),
                "addition": statistics.median(metric.addition for metric in transitions),
                "modification_burden": (
                    statistics.median(
                        float(metric.modification_burden) for metric in dose_resolved
                    )
                    if dose_resolved
                    else None
                ),
                "mode_proportions": (
                    {
                        mode: mode_counts[mode] / len(dose_resolved)
                        for mode in TRANSITION_MODES
                    }
                    if dose_resolved
                    else {}
                ),
            }
        )

    longitudinal_rows: list[dict[str, object]] = []
    mode_rows: list[dict[str, object]] = []
    for group in group_names:
        summaries = patient_summaries[group]
        dose_summaries = [
            row for row in summaries if row["modification_burden"] is not None
        ]
        longitudinal_rows.append(
            {
                "group": group,
                "repeat_patients": len(summaries),
                "transitions": sum(int(row["transition_n"]) for row in summaries),
                "dose_resolved_patients": len(dose_summaries),
                "dose_resolved_transitions": sum(
                    int(row["dose_transition_n"]) for row in dose_summaries
                ),
                "median_patient_jaccard": _median([float(row["jaccard"]) for row in summaries]),
                "median_patient_retention": _median([float(row["retention"]) for row in summaries]),
                "median_patient_addition": _median([float(row["addition"]) for row in summaries]),
                "median_patient_modification_burden": _median(
                    [float(row["modification_burden"]) for row in dose_summaries]
                ),
            }
        )
        for mode in TRANSITION_MODES:
            mode_rows.append(
                {
                    "group": group,
                    "mode": mode,
                    "dose_resolved_patients": len(dose_summaries),
                    "dose_resolved_transitions": sum(
                        int(row["dose_transition_n"]) for row in dose_summaries
                    ),
                    "mean_patient_proportion": _mean(
                        [float(row["mode_proportions"][mode]) for row in dose_summaries]
                    ),
                }
            )
    return longitudinal_rows, mode_rows


def _longitudinal_item_change_rows(
    visits_by_patient: dict[str, tuple[PrescriptionVisit, ...]],
    group_names: tuple[str, ...],
    min_public_n: int,
) -> list[dict[str, object]]:
    patient_changes: dict[str, list[dict[str, object]]] = {
        group: [] for group in group_names
    }
    for visits in visits_by_patient.values():
        if len(visits) < 2:
            continue
        transition_n = len(visits) - 1
        added_counts: Counter[str] = Counter()
        removed_counts: Counter[str] = Counter()
        added_doses: dict[str, list[float]] = defaultdict(list)
        removed_doses: dict[str, list[float]] = defaultdict(list)
        for previous, current in itertools.pairwise(visits):
            added = current.items - previous.items
            removed = previous.items - current.items
            added_counts.update(added)
            removed_counts.update(removed)
            for item in added:
                dose = _gram_dose(current, item)
                if dose is not None:
                    added_doses[item].append(dose)
            for item in removed:
                dose = _gram_dose(previous, item)
                if dose is not None:
                    removed_doses[item].append(dose)
        patient_changes[visits[0].group].append(
            {
                "addition": {
                    item: count / transition_n for item, count in added_counts.items()
                },
                "removal": {
                    item: count / transition_n for item, count in removed_counts.items()
                },
                "addition_doses": {
                    item: mode
                    for item, values in added_doses.items()
                    if (mode := _unique_mode(values)) is not None
                },
                "removal_doses": {
                    item: mode
                    for item, values in removed_doses.items()
                    if (mode := _unique_mode(values)) is not None
                },
            }
        )

    rows: list[dict[str, object]] = []
    group_order = {group: index for index, group in enumerate(group_names)}
    direction_order = {"addition": 0, "removal": 1}
    for group in group_names:
        summaries = patient_changes[group]
        repeat_patients = len(summaries)
        for change_type in direction_order:
            items = set().union(
                *(
                    summary[change_type].keys()
                    for summary in summaries
                    if isinstance(summary[change_type], dict)
                )
            )
            for item in items:
                rates = [
                    float(summary[change_type].get(item, 0.0))
                    for summary in summaries
                    if isinstance(summary[change_type], dict)
                ]
                patients_with_change = sum(rate > 0 for rate in rates)
                if patients_with_change < min_public_n:
                    continue
                dose_key = f"{change_type}_doses"
                patient_doses = [
                    float(summary[dose_key][item])
                    for summary in summaries
                    if isinstance(summary[dose_key], dict)
                    and item in summary[dose_key]
                ]
                rows.append(
                    {
                        "group": group,
                        "item_name": item,
                        "change_type": change_type,
                        "repeat_patients": repeat_patients,
                        "patients_with_change": patients_with_change,
                        "patient_prevalence": patients_with_change / repeat_patients,
                        "mean_patient_transition_fraction": statistics.fmean(rates),
                        **_dose_mode_summary(patient_doses, min_public_n),
                    }
                )
    rows.sort(
        key=lambda row: (
            group_order[str(row["group"])],
            direction_order[str(row["change_type"])],
            -float(row["patient_prevalence"]),
            -float(row["mean_patient_transition_fraction"]),
            str(row["item_name"]),
        )
    )
    return rows


def _age_on_date(birth_date: date, index_date: date) -> int | None:
    age = index_date.year - birth_date.year - (
        (index_date.month, index_date.day) < (birth_date.month, birth_date.day)
    )
    return age if 0 <= age <= 130 else None


def _clinical_patient_year_rows(
    visits_by_patient: dict[str, tuple[PrescriptionVisit, ...]],
    group_names: tuple[str, ...],
    min_public_n: int,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    group_year_patients: dict[tuple[str, int], set[str]] = defaultdict(set)
    group_year_visits: Counter[tuple[str, int]] = Counter()
    group_year_index_items: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    group_year_index_doses: dict[
        tuple[str, int], dict[str, list[float]]
    ] = defaultdict(lambda: defaultdict(list))
    patient_year_changes: dict[
        tuple[str, int], dict[str, dict[str, object]]
    ] = defaultdict(dict)

    for patient_id, visits in visits_by_patient.items():
        if not visits:
            continue
        group = visits[0].group
        visits_by_year: dict[int, list[PrescriptionVisit]] = defaultdict(list)
        for visit in visits:
            visits_by_year[visit.visit_date.year].append(visit)
        for year, annual_visits in visits_by_year.items():
            key = (group, year)
            group_year_patients[key].add(patient_id)
            group_year_visits[key] += len(annual_visits)
            annual_index = annual_visits[0]
            group_year_index_items[key].update(annual_index.items)
            for item in annual_index.items:
                dose = _gram_dose(annual_index, item)
                if dose is not None:
                    group_year_index_doses[key][item].append(dose)

        for previous, current in itertools.pairwise(visits):
            key = (group, current.visit_date.year)
            patient_summary = patient_year_changes[key].setdefault(
                patient_id,
                {
                    "transition_n": 0,
                    "addition": Counter(),
                    "removal": Counter(),
                    "addition_doses": defaultdict(list),
                    "removal_doses": defaultdict(list),
                },
            )
            patient_summary["transition_n"] = int(
                patient_summary["transition_n"]
            ) + 1
            addition_counts = patient_summary["addition"]
            removal_counts = patient_summary["removal"]
            if not isinstance(addition_counts, Counter) or not isinstance(
                removal_counts, Counter
            ):
                raise TypeError("Patient-year change counters are invalid.")
            addition_counts.update(current.items - previous.items)
            removal_counts.update(previous.items - current.items)
            addition_doses = patient_summary["addition_doses"]
            removal_doses = patient_summary["removal_doses"]
            if not isinstance(addition_doses, defaultdict) or not isinstance(
                removal_doses, defaultdict
            ):
                raise TypeError("Patient-year dose collections are invalid.")
            for item in current.items - previous.items:
                dose = _gram_dose(current, item)
                if dose is not None:
                    addition_doses[item].append(dose)
            for item in previous.items - current.items:
                dose = _gram_dose(previous, item)
                if dose is not None:
                    removal_doses[item].append(dose)

    group_order = {group: index for index, group in enumerate(group_names)}
    public_group_years = {
        key
        for key, patients in group_year_patients.items()
        if len(patients) >= min_public_n
    }
    summary_rows: list[dict[str, object]] = []
    item_rows: list[dict[str, object]] = []
    change_rows: list[dict[str, object]] = []

    for group, year in sorted(
        public_group_years, key=lambda key: (group_order[key[0]], key[1])
    ):
        key = (group, year)
        patients = len(group_year_patients[key])
        repeat_patients = len(patient_year_changes.get(key, {}))
        repeat_public = repeat_patients == 0 or repeat_patients >= min_public_n
        transitions = sum(
            int(summary["transition_n"])
            for summary in patient_year_changes.get(key, {}).values()
        )
        summary_rows.append(
            {
                "group": group,
                "year": year,
                "patients": patients,
                "repeat_patients": repeat_patients if repeat_public else None,
                "visits": group_year_visits[key],
                "transitions": transitions if repeat_public else None,
            }
        )
        for item, count in sorted(
            group_year_index_items[key].items(),
            key=lambda pair: (-pair[1], pair[0]),
        ):
            if count < min_public_n:
                continue
            item_rows.append(
                {
                    "group": group,
                    "year": year,
                    "item_name": item,
                    "exposed_patients": count,
                    "group_patients": patients,
                    "prevalence": count / patients,
                    **_dose_mode_summary(
                        group_year_index_doses[key][item], min_public_n
                    ),
                }
            )

        if not repeat_public or repeat_patients == 0:
            continue
        patient_summaries = patient_year_changes[key]
        for change_type in ("addition", "removal"):
            items = set().union(
                *(
                    summary[change_type].keys()
                    for summary in patient_summaries.values()
                    if isinstance(summary[change_type], Counter)
                )
            )
            for item in items:
                rates = []
                for summary in patient_summaries.values():
                    counts = summary[change_type]
                    if not isinstance(counts, Counter):
                        raise TypeError("Patient-year item counter is invalid.")
                    rates.append(
                        counts[item] / int(summary["transition_n"])
                    )
                patients_with_change = sum(rate > 0 for rate in rates)
                if patients_with_change < min_public_n:
                    continue
                dose_key = f"{change_type}_doses"
                patient_doses: list[float] = []
                for summary in patient_summaries.values():
                    dose_values = summary[dose_key]
                    if not isinstance(dose_values, defaultdict):
                        raise TypeError("Patient-year dose collection is invalid.")
                    if dose_values.get(item):
                        mode = _unique_mode(dose_values[item])
                        if mode is not None:
                            patient_doses.append(mode)
                change_rows.append(
                    {
                        "group": group,
                        "year": year,
                        "item_name": item,
                        "change_type": change_type,
                        "repeat_patients": repeat_patients,
                        "patients_with_change": patients_with_change,
                        "patient_prevalence": patients_with_change
                        / repeat_patients,
                        "mean_patient_transition_fraction": statistics.fmean(
                            rates
                        ),
                        **_dose_mode_summary(patient_doses, min_public_n),
                    }
                )

    change_rows.sort(
        key=lambda row: (
            group_order[str(row["group"])],
            int(row["year"]),
            str(row["change_type"]),
            -float(row["mean_patient_transition_fraction"]),
            str(row["item_name"]),
        )
    )
    return summary_rows, item_rows, change_rows


def analyze_clinical_phenotypes(
    visit_result: VisitBuildResult,
    cohort: ClinicalPhenotypeCohortResult,
    demographics: dict[str, PatientDemographics],
    config: AnalysisConfig,
) -> AnalysisResult:
    if not config.clinical_phenotype_analysis.enabled:
        return AnalysisResult(tables={}, metadata={"enabled": False}, warnings=())

    visits_by_patient = visit_result.visits_by_patient
    group_position = {
        group.name: index for index, group in enumerate(config.groups)
    }
    group_names = tuple(
        sorted(
            cohort.group_components,
            key=lambda group: (
                len(cohort.group_components[group]),
                tuple(group_position[item] for item in cohort.group_components[group]),
            ),
        )
    )
    clinical = config.clinical_phenotype_analysis
    patient_ages: dict[str, int] = {}
    for patient_id, visits in visits_by_patient.items():
        demographic = demographics.get(patient_id)
        if demographic is None or demographic.birth_date is None or not visits:
            continue
        age = _age_on_date(demographic.birth_date, visits[0].visit_date)
        if age is not None:
            patient_ages[patient_id] = age

    strata: list[tuple[str, str, str, set[str]]] = [
        ("overall", "all", "All patients", set(visits_by_patient))
    ]
    for category, label in clinical.sex_labels.items():
        strata.append(
            (
                "sex",
                category,
                label,
                {
                    patient_id
                    for patient_id in visits_by_patient
                    if demographics.get(patient_id) is not None
                    and demographics[patient_id].sex == category
                },
            )
        )
    for band in clinical.age_bands:
        strata.append(
            (
                "age_band",
                band.name,
                band.label,
                {
                    patient_id
                    for patient_id, age in patient_ages.items()
                    if band.min_age <= age <= band.max_age
                },
            )
        )

    summary_rows: list[dict[str, object]] = []
    item_rows: list[dict[str, object]] = []
    combination_rows: list[dict[str, object]] = []
    longitudinal_rows: list[dict[str, object]] = []
    change_rows: list[dict[str, object]] = []
    year_summary_rows: list[dict[str, object]] = []
    year_item_rows: list[dict[str, object]] = []
    year_change_rows: list[dict[str, object]] = []

    def context_fields(
        group: str, stratum_type: str, stratum: str, stratum_label: str
    ) -> dict[str, object]:
        components = cohort.group_components[group]
        return {
            "group": group,
            "group_label": cohort.group_labels[group],
            "components": ";".join(components),
            "disease_count": len(components),
            "stratum_type": stratum_type,
            "stratum": stratum,
            "stratum_label": stratum_label,
        }

    for stratum_type, stratum, stratum_label, patient_ids in strata:
        subset = {
            patient_id: visits
            for patient_id, visits in visits_by_patient.items()
            if patient_id in patient_ids
        }
        first_visits = _first_visits(subset)
        counts, prevalence, denominators = _prevalence(first_visits, group_names)
        public_items, _ = _first_prescription_rows(
            counts, prevalence, denominators, first_visits, config.min_public_n
        )
        for row in public_items:
            item_rows.append(
                {
                    **context_fields(
                        str(row["group"]), stratum_type, stratum, stratum_label
                    ),
                    **{key: value for key, value in row.items() if key != "group"},
                }
            )

        public_combinations, _, _ = _frequent_combination_rows(
            first_visits, config, group_names
        )
        for row in public_combinations:
            combination_rows.append(
                {
                    **context_fields(
                        str(row["group"]), stratum_type, stratum, stratum_label
                    ),
                    **{key: value for key, value in row.items() if key != "group"},
                }
            )

        stratum_longitudinal, _ = _longitudinal_rows(subset, group_names)
        for row in stratum_longitudinal:
            if int(row["repeat_patients"]) < config.min_public_n:
                continue
            longitudinal_rows.append(
                {
                    **context_fields(
                        str(row["group"]), stratum_type, stratum, stratum_label
                    ),
                    **{key: value for key, value in row.items() if key != "group"},
                }
            )

        stratum_changes = _longitudinal_item_change_rows(
            subset, group_names, config.min_public_n
        )
        for row in stratum_changes:
            change_rows.append(
                {
                    **context_fields(
                        str(row["group"]), stratum_type, stratum, stratum_label
                    ),
                    **{key: value for key, value in row.items() if key != "group"},
                }
            )

        (
            stratum_year_summary,
            stratum_year_items,
            stratum_year_changes,
        ) = _clinical_patient_year_rows(subset, group_names, config.min_public_n)
        for destination, rows in (
            (year_summary_rows, stratum_year_summary),
            (year_item_rows, stratum_year_items),
            (year_change_rows, stratum_year_changes),
        ):
            for row in rows:
                destination.append(
                    {
                        **context_fields(
                            str(row["group"]),
                            stratum_type,
                            stratum,
                            stratum_label,
                        ),
                        **{
                            key: value
                            for key, value in row.items()
                            if key != "group"
                        },
                    }
                )

        for row in _cohort_summary(subset, group_names):
            group = str(row["group"])
            patients = int(row["patients"])
            if patients < config.min_public_n:
                continue
            group_patient_ids = [
                patient_id
                for patient_id, visits in subset.items()
                if visits and visits[0].group == group
            ]
            ages = sorted(
                patient_ages[patient_id]
                for patient_id in group_patient_ids
                if patient_id in patient_ages
            )
            age_public = len(ages) >= config.min_public_n
            quartiles = (
                statistics.quantiles(ages, n=4, method="inclusive")
                if age_public and len(ages) >= 2
                else (None, None, None)
            )
            repeat_patients = int(row["repeat_patients"])
            repeat_public = repeat_patients == 0 or repeat_patients >= config.min_public_n
            selected_age_band = next(
                (
                    band
                    for band in clinical.age_bands
                    if stratum_type == "age_band" and band.name == stratum
                ),
                None,
            )
            summary_rows.append(
                {
                    **context_fields(group, stratum_type, stratum, stratum_label),
                    "patients": patients,
                    "repeat_patients": repeat_patients if repeat_public else None,
                    "visits": row["visits"],
                    "transitions": row["transitions"] if repeat_public else None,
                    "known_age_patients": len(ages) if age_public else None,
                    "median_age": statistics.median(ages) if age_public else None,
                    "age_q1": quartiles[0] if age_public else None,
                    "age_q3": quartiles[2] if age_public else None,
                    "age_min": (
                        selected_age_band.min_age
                        if selected_age_band is not None
                        else None
                    ),
                    "age_max": (
                        selected_age_band.max_age
                        if selected_age_band is not None
                        else None
                    ),
                }
            )

    change_index = {
        (
            str(row["group"]),
            str(row["stratum_type"]),
            str(row["stratum"]),
            str(row["change_type"]),
            str(row["item_name"]),
        ): row
        for row in change_rows
    }
    comparison_rows: list[dict[str, object]] = []
    for combination_group in group_names:
        components = cohort.group_components[combination_group]
        if len(components) < 2:
            continue
        for single_group in components:
            if single_group not in cohort.group_components:
                continue
            for key, combination_row in change_index.items():
                group, stratum_type, stratum, change_type, item = key
                if group != combination_group:
                    continue
                single_row = change_index.get(
                    (single_group, stratum_type, stratum, change_type, item)
                )
                if single_row is None:
                    continue
                difference = float(combination_row["patient_prevalence"]) - float(
                    single_row["patient_prevalence"]
                )
                frequency_difference = float(
                    combination_row["mean_patient_transition_fraction"]
                ) - float(single_row["mean_patient_transition_fraction"])
                comparison_rows.append(
                    {
                        "combination_group": combination_group,
                        "combination_label": cohort.group_labels[combination_group],
                        "single_group": single_group,
                        "single_label": cohort.group_labels[single_group],
                        "stratum_type": stratum_type,
                        "stratum": stratum,
                        "stratum_label": combination_row["stratum_label"],
                        "change_type": change_type,
                        "item_name": item,
                        "combination_repeat_patients": combination_row[
                            "repeat_patients"
                        ],
                        "combination_patients_with_change": combination_row[
                            "patients_with_change"
                        ],
                        "combination_prevalence": combination_row[
                            "patient_prevalence"
                        ],
                        "single_repeat_patients": single_row["repeat_patients"],
                        "single_patients_with_change": single_row[
                            "patients_with_change"
                        ],
                        "single_prevalence": single_row["patient_prevalence"],
                        "prevalence_difference": difference,
                        "combination_mean_transition_fraction": combination_row[
                            "mean_patient_transition_fraction"
                        ],
                        "single_mean_transition_fraction": single_row[
                            "mean_patient_transition_fraction"
                        ],
                        "mean_transition_fraction_difference": frequency_difference,
                        "combination_dose_patients": combination_row[
                            "dose_patients"
                        ],
                        "combination_most_common_dose_values_g": combination_row[
                            "most_common_dose_values_g"
                        ],
                        "combination_most_common_dose_patients": combination_row[
                            "most_common_dose_patients"
                        ],
                        "combination_most_common_dose_fraction": combination_row[
                            "most_common_dose_fraction"
                        ],
                        "combination_most_common_dose_tied": combination_row[
                            "most_common_dose_tied"
                        ],
                        "single_dose_patients": single_row["dose_patients"],
                        "single_most_common_dose_values_g": single_row[
                            "most_common_dose_values_g"
                        ],
                        "single_most_common_dose_patients": single_row[
                            "most_common_dose_patients"
                        ],
                        "single_most_common_dose_fraction": single_row[
                            "most_common_dose_fraction"
                        ],
                        "single_most_common_dose_tied": single_row[
                            "most_common_dose_tied"
                        ],
                        "higher_frequency": (
                            "combination"
                            if frequency_difference > 0
                            else "single" if frequency_difference < 0 else "equal"
                        ),
                    }
                )

    comparison_rows.sort(
        key=lambda row: (
            group_names.index(str(row["combination_group"])),
            group_names.index(str(row["single_group"])),
            str(row["stratum_type"]),
            str(row["stratum"]),
            str(row["change_type"]),
            -abs(float(row["mean_transition_fraction_difference"])),
            str(row["item_name"]),
        )
    )
    return AnalysisResult(
        tables={
            "clinical_phenotype_summary": summary_rows,
            "clinical_first_prescription_item_prevalence": item_rows,
            "clinical_frequent_item_combinations": combination_rows,
            "clinical_longitudinal_summary": longitudinal_rows,
            "clinical_item_change_tendency": change_rows,
            "clinical_item_change_comparison": comparison_rows,
            "clinical_year_summary": year_summary_rows,
            "clinical_year_item_prevalence": year_item_rows,
            "clinical_year_item_change_tendency": year_change_rows,
        },
        metadata={
            "enabled": True,
            "assigned_patients": len(cohort.patient_groups),
            "analyzable_patients": len(visits_by_patient),
            "target_patients": cohort.target_patients,
            "other_disease_excluded_patients": (
                cohort.other_disease_excluded_patients
            ),
            "phenotype_group_counts": cohort.group_counts,
            "public_summary_rows": len(summary_rows),
            "public_change_rows": len(change_rows),
            "public_comparison_rows": len(comparison_rows),
            "public_year_summary_rows": len(year_summary_rows),
            "public_year_item_rows": len(year_item_rows),
            "public_year_change_rows": len(year_change_rows),
        },
        warnings=cohort.warnings,
    )


def _cross_group_rows(
    group_names: tuple[str, ...],
    counts: dict[str, Counter[str]],
    prevalence: dict[str, dict[str, float]],
    min_public_n: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    all_items = set().union(*(group_counts.keys() for group_counts in counts.values()))
    public_items = {
        item
        for item in all_items
        if all(counts[group][item] >= min_public_n for group in group_names)
    }
    for left, right in itertools.combinations(group_names, 2):
        rows.append(
            {
                "group_left": left,
                "group_right": right,
                "common_public_items": len(public_items),
                "weighted_jaccard": _weighted_jaccard(
                    prevalence[left], prevalence[right], public_items
                ),
                "jensen_shannon_distance": _jensen_shannon_distance(
                    prevalence[left], prevalence[right], public_items
                ),
            }
        )
    return rows


@dataclass(frozen=True)
class _MatchedTransition:
    observed_jaccard: float
    matched_between_jaccard: float
    control_patient_n: int
    match_level: str
    control_values_by_patient: tuple[tuple[float, ...], ...]


def _visit_stage(index: int) -> str:
    if index == 2:
        return "second"
    if index <= 5:
        return "third_to_fifth"
    return "sixth_or_later"


def _set_jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _bootstrap_median(
    values: list[float], replicates: int, rng: random.Random
) -> tuple[float, float]:
    draws = [
        statistics.median(rng.choice(values) for _ in values)
        for _ in range(replicates)
    ]
    return _percentile(draws, 0.025), _percentile(draws, 0.975)


def _bh_adjust(p_values: list[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 1.0
    for reverse_rank, index in enumerate(reversed(order), start=1):
        rank = len(p_values) - reverse_rank + 1
        running = min(running, p_values[index] * len(p_values) / rank)
        adjusted[index] = running
    return adjusted


def _choose_match_candidates(
    current: PrescriptionVisit,
    current_index: int,
    physician_key: str,
    by_exact: dict[tuple[str, str, int, str, int], list[PrescriptionVisit]],
    by_stage: dict[tuple[str, str, int, str], list[PrescriptionVisit]],
    by_year: dict[tuple[str, str, int], list[PrescriptionVisit]],
) -> tuple[list[PrescriptionVisit], str]:
    stage = _visit_stage(current_index)
    size = len(current.items)
    exact = [
        visit
        for visit in by_exact.get(
            (physician_key, current.group, current.visit_date.year, stage, size), []
        )
        if visit.patient_id != current.patient_id
    ]
    if exact:
        return exact, "exact_year_stage_size"

    stage_pool = [
        visit
        for visit in by_stage.get(
            (physician_key, current.group, current.visit_date.year, stage), []
        )
        if visit.patient_id != current.patient_id
    ]
    if stage_pool:
        distance = min(abs(len(visit.items) - size) for visit in stage_pool)
        return (
            [visit for visit in stage_pool if abs(len(visit.items) - size) == distance],
            "nearest_size_same_year_stage",
        )

    year_pool = [
        visit
        for visit in by_year.get(
            (physician_key, current.group, current.visit_date.year), []
        )
        if visit.patient_id != current.patient_id
    ]
    if year_pool:
        distance = min(abs(len(visit.items) - size) for visit in year_pool)
        return (
            [visit for visit in year_pool if abs(len(visit.items) - size) == distance],
            "nearest_size_same_year",
        )
    return [], "unmatched"


def _matched_control_distribution(
    previous: PrescriptionVisit, candidates: list[PrescriptionVisit]
) -> tuple[float, tuple[tuple[float, ...], ...]]:
    values_by_patient: dict[str, list[float]] = defaultdict(list)
    for candidate in candidates:
        values_by_patient[candidate.patient_id].append(
            _set_jaccard(previous.items, candidate.items)
        )
    control_values = tuple(tuple(values) for values in values_by_patient.values())
    return (
        statistics.median(statistics.median(values) for values in control_values),
        control_values,
    )


def _matched_patient_summaries(
    patient_transitions: dict[str, list[_MatchedTransition]],
) -> list[tuple[float, float, float, list[_MatchedTransition]]]:
    rows: list[tuple[float, float, float, list[_MatchedTransition]]] = []
    for transitions in patient_transitions.values():
        observed = statistics.median(
            transition.observed_jaccard for transition in transitions
        )
        between = statistics.median(
            transition.matched_between_jaccard for transition in transitions
        )
        rows.append((observed, between, observed - between, transitions))
    return rows


def _matched_sensitivity_rows(
    transitions_by_group: dict[str, dict[str, list[_MatchedTransition]]],
    config: AnalysisConfig,
) -> tuple[list[dict[str, object]], list[str]]:
    matching = config.matched_reference
    variants = (
        (
            "exact_year_stage_size_only",
            lambda transition: transition.match_level == "exact_year_stage_size",
        ),
        (
            "minimum_5_control_patients",
            lambda transition: transition.control_patient_n >= 5,
        ),
    )
    rng = random.Random(matching.random_seed + 2)
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    for analysis_name, keep_transition in variants:
        for group_rule in config.groups:
            group = group_rule.name
            restricted = {
                patient_id: [
                    transition
                    for transition in transitions
                    if keep_transition(transition)
                ]
                for patient_id, transitions in transitions_by_group[group].items()
            }
            restricted = {
                patient_id: transitions
                for patient_id, transitions in restricted.items()
                if transitions
            }
            if len(restricted) < config.min_public_n:
                warnings.append(
                    f"Matched sensitivity {analysis_name} for {group} is not "
                    "reportable below min_public_n"
                )
                continue

            patient_rows = _matched_patient_summaries(restricted)
            observed_values = [row[0] for row in patient_rows]
            between_values = [row[1] for row in patient_rows]
            difference_values = [row[2] for row in patient_rows]
            difference_ci = _bootstrap_median(
                difference_values, matching.bootstrap_replicates, rng
            )
            rows.append(
                {
                    "analysis": analysis_name,
                    "group": group,
                    "patients": len(patient_rows),
                    "transitions": sum(len(row[3]) for row in patient_rows),
                    "observed_patient_median_jaccard": statistics.median(
                        observed_values
                    ),
                    "matched_between_patient_median_jaccard": statistics.median(
                        between_values
                    ),
                    "within_minus_between_median": statistics.median(
                        difference_values
                    ),
                    "within_minus_between_bootstrap_ci95_low": difference_ci[0],
                    "within_minus_between_bootstrap_ci95_high": difference_ci[1],
                }
            )
    return rows, warnings


def _matched_reference_rows(
    visits_by_patient: dict[str, tuple[PrescriptionVisit, ...]],
    config: AnalysisConfig,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
    list[str],
]:
    matching = config.matched_reference
    metadata: dict[str, object] = {
        "enabled": matching.enabled,
        "assume_single_physician": matching.assume_single_physician,
        "random_seed": matching.random_seed,
        "bootstrap_replicates": matching.bootstrap_replicates,
        "null_replicates": matching.null_replicates,
    }
    if not matching.enabled:
        return [], [], metadata, []

    all_visits = [visit for visits in visits_by_patient.values() for visit in visits]
    if not matching.assume_single_physician and any(
        not visit.physician_id for visit in all_visits
    ):
        raise InputError(
            "Matched reference requires physician_id or assume_single_physician=true"
        )

    def physician_key(visit: PrescriptionVisit) -> str:
        return "__assumed_single_physician__" if matching.assume_single_physician else visit.physician_id

    by_exact: dict[
        tuple[str, str, int, str, int], list[PrescriptionVisit]
    ] = defaultdict(list)
    by_stage: dict[tuple[str, str, int, str], list[PrescriptionVisit]] = defaultdict(list)
    by_year: dict[tuple[str, str, int], list[PrescriptionVisit]] = defaultdict(list)
    for visits in visits_by_patient.values():
        for index, visit in enumerate(visits, start=1):
            if index < 2:
                continue
            key = physician_key(visit)
            stage = _visit_stage(index)
            size = len(visit.items)
            by_exact[(key, visit.group, visit.visit_date.year, stage, size)].append(visit)
            by_stage[(key, visit.group, visit.visit_date.year, stage)].append(visit)
            by_year[(key, visit.group, visit.visit_date.year)].append(visit)

    transitions_by_group: dict[
        str, dict[str, list[_MatchedTransition]]
    ] = defaultdict(lambda: defaultdict(list))
    potential = Counter()
    unmatched = Counter()
    for patient_id, visits in visits_by_patient.items():
        for current_index, (previous, current) in enumerate(
            itertools.pairwise(visits), start=2
        ):
            group = current.group
            potential[group] += 1
            previous_physician = physician_key(previous)
            current_physician = physician_key(current)
            if previous_physician != current_physician:
                unmatched[group] += 1
                continue
            candidates, match_level = _choose_match_candidates(
                current,
                current_index,
                current_physician,
                by_exact,
                by_stage,
                by_year,
            )
            if not candidates:
                unmatched[group] += 1
                continue

            matched_between, control_values = _matched_control_distribution(
                previous, candidates
            )
            transitions_by_group[group][patient_id].append(
                _MatchedTransition(
                    observed_jaccard=_set_jaccard(previous.items, current.items),
                    matched_between_jaccard=matched_between,
                    control_patient_n=len(control_values),
                    match_level=match_level,
                    control_values_by_patient=control_values,
                )
            )

    rng = random.Random(matching.random_seed)
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    p_values: list[float] = []
    for group_rule in config.groups:
        group = group_rule.name
        patient_transitions = transitions_by_group[group]
        if len(patient_transitions) < config.min_public_n:
            warnings.append(
                f"Matched reference for {group} is not reportable below min_public_n"
            )
            continue

        patient_rows = _matched_patient_summaries(patient_transitions)

        observed_values = [row[0] for row in patient_rows]
        between_values = [row[1] for row in patient_rows]
        difference_values = [row[2] for row in patient_rows]
        observed_ci = _bootstrap_median(
            observed_values, matching.bootstrap_replicates, rng
        )
        between_ci = _bootstrap_median(
            between_values, matching.bootstrap_replicates, rng
        )
        difference_ci = _bootstrap_median(
            difference_values, matching.bootstrap_replicates, rng
        )

        observed_group_median = statistics.median(observed_values)
        exceedances = 0
        for _ in range(matching.null_replicates):
            null_patient_values: list[float] = []
            for _, _, _, transitions in patient_rows:
                sampled_transitions = [
                    rng.choice(rng.choice(transition.control_values_by_patient))
                    for transition in transitions
                ]
                null_patient_values.append(statistics.median(sampled_transitions))
            if statistics.median(null_patient_values) >= observed_group_median:
                exceedances += 1
        empirical_p = (exceedances + 1) / (matching.null_replicates + 1)
        p_values.append(empirical_p)

        matched_transitions = [
            transition
            for transitions in patient_transitions.values()
            for transition in transitions
        ]
        rows.append(
            {
                "group": group,
                "patients": len(patient_rows),
                "matched_transitions": len(matched_transitions),
                "potential_transitions": potential[group],
                "unmatched_transitions": unmatched[group],
                "matchable_transition_pct": (
                    100 * len(matched_transitions) / potential[group]
                    if potential[group]
                    else None
                ),
                "exact_year_stage_size_match_pct": 100
                * sum(
                    transition.match_level == "exact_year_stage_size"
                    for transition in matched_transitions
                )
                / len(matched_transitions),
                "eligible_control_patients_median": statistics.median(
                    transition.control_patient_n for transition in matched_transitions
                ),
                "observed_patient_median_jaccard": observed_group_median,
                "observed_bootstrap_ci95_low": observed_ci[0],
                "observed_bootstrap_ci95_high": observed_ci[1],
                "matched_between_patient_median_jaccard": statistics.median(
                    between_values
                ),
                "matched_between_bootstrap_ci95_low": between_ci[0],
                "matched_between_bootstrap_ci95_high": between_ci[1],
                "within_minus_between_median": statistics.median(difference_values),
                "within_minus_between_bootstrap_ci95_low": difference_ci[0],
                "within_minus_between_bootstrap_ci95_high": difference_ci[1],
                "empirical_one_sided_p": empirical_p,
                "empirical_one_sided_bh_fdr": None,
            }
        )

    for row, adjusted in zip(rows, _bh_adjust(p_values), strict=True):
        row["empirical_one_sided_bh_fdr"] = adjusted
    metadata["reported_groups"] = len(rows)
    metadata["matched_patients"] = sum(int(row["patients"]) for row in rows)
    metadata["matched_transitions"] = sum(
        int(row["matched_transitions"]) for row in rows
    )
    sensitivity_rows, sensitivity_warnings = _matched_sensitivity_rows(
        transitions_by_group, config
    )
    metadata["sensitivity_seed"] = matching.random_seed + 2
    metadata["sensitivity_reported_rows"] = len(sensitivity_rows)
    return rows, sensitivity_rows, metadata, [*warnings, *sensitivity_warnings]


def _temporal_rows(
    first_visits: dict[str, PrescriptionVisit],
    config: AnalysisConfig,
    cutpoints: tuple[int, ...],
) -> tuple[list[dict[str, object]], list[str]]:
    group_names = tuple(group.name for group in config.groups)
    rows: list[dict[str, object]] = []
    warnings: list[str] = []
    for cutpoint in cutpoints:
        period_visits: dict[tuple[str, str], list[PrescriptionVisit]] = defaultdict(
            list
        )
        for visit in first_visits.values():
            period = "early" if visit.visit_date.year <= cutpoint else "late"
            period_visits[(visit.group, period)].append(visit)

        for group in group_names:
            early = period_visits[(group, "early")]
            late = period_visits[(group, "late")]
            enough_patients = (
                len(early) >= config.min_public_n
                and len(late) >= config.min_public_n
            )
            if not enough_patients:
                warnings.append(
                    f"Temporal metrics for {group} at cutpoint {cutpoint} are not "
                    "reportable below min_public_n"
                )
                rows.append(
                    {
                        "group": group,
                        "early_end_year": cutpoint,
                        "early_patients": None,
                        "late_patients": None,
                        "item_universe_items": None,
                        "weighted_jaccard": None,
                        "jensen_shannon_distance": None,
                        "early_core_items": None,
                        "retained_core_items": None,
                        "core_retention_fraction": None,
                    }
                )
                continue

            early_counts = Counter(item for visit in early for item in visit.items)
            late_counts = Counter(item for visit in late for item in visit.items)
            early_prev = {
                item: count / len(early) for item, count in early_counts.items()
            }
            late_prev = {
                item: count / len(late) for item, count in late_counts.items()
            }
            items = set(early_counts) | set(late_counts)
            early_core = {
                item
                for item, count in early_counts.items()
                if count >= config.min_public_n
                and early_prev[item] >= config.core_prevalence
            }
            retained_core = {
                item
                for item in early_core
                if late_prev.get(item, 0.0) >= config.core_prevalence
            }
            rows.append(
                {
                    "group": group,
                    "early_end_year": cutpoint,
                    "early_patients": len(early),
                    "late_patients": len(late),
                    "item_universe_items": len(items),
                    "weighted_jaccard": _weighted_jaccard(
                        early_prev, late_prev, items
                    ),
                    "jensen_shannon_distance": _jensen_shannon_distance(
                        early_prev, late_prev, items
                    ),
                    "early_core_items": len(early_core),
                    "retained_core_items": len(retained_core),
                    "core_retention_fraction": (
                        len(retained_core) / len(early_core) if early_core else None
                    ),
                }
            )
    return rows, warnings


def _item_normalization_rows(
    visit_result: VisitBuildResult, config: AnalysisConfig
) -> list[dict[str, object]]:
    normalization = config.item_normalization
    return [
        {
            "dictionary_version": normalization.version,
            "dictionary_sha256": normalization.dictionary_sha256,
            "dictionary_entries": len(normalization.mappings),
            "eligible_item_lines": visit_result.eligible_item_line_count,
            "distinct_source_items": visit_result.distinct_source_item_count,
            "dictionary_matched_item_lines": (
                visit_result.dictionary_matched_item_line_count
            ),
            "dictionary_matched_source_items": (
                visit_result.dictionary_matched_source_item_count
            ),
            "unmapped_source_items": (
                visit_result.distinct_source_item_count
                - visit_result.dictionary_matched_source_item_count
            ),
            "changed_item_lines": visit_result.changed_item_line_count,
            "canonical_items": visit_result.canonical_item_count,
            "canonical_collision_visit_items": (
                visit_result.canonical_collision_visit_item_count
            ),
        }
    ]


def _dose_conflict_rows(
    visit_result: VisitBuildResult,
    group_names: tuple[str, ...],
    min_public_n: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    suppressed_groups = {
        group
        for group in group_names
        if 0
        < visit_result.dose_conflict_patients_by_group.get(group, 0)
        < min_public_n
    }
    if suppressed_groups:
        secondary_candidates = [
            group
            for group in group_names
            if visit_result.dose_conflict_patients_by_group.get(group, 0)
            >= min_public_n
        ]
        if secondary_candidates:
            suppressed_groups.add(
                min(
                    secondary_candidates,
                    key=lambda group: visit_result.dose_conflict_patients_by_group[
                        group
                    ],
                )
            )
    for group in (*group_names, "all"):
        group_visits = [
            visits
            for visits in visit_result.visits_by_patient.values()
            if visits and (group == "all" or visits[0].group == group)
        ]
        patients = len(group_visits)
        visits = sum(len(patient_visits) for patient_visits in group_visits)
        if group == "all":
            conflict_patients = sum(
                visit_result.dose_conflict_patients_by_group.values()
            )
            conflict_visits = sum(
                visit_result.dose_conflict_visits_by_group.values()
            )
            conflict_items = sum(visit_result.dose_conflict_items_by_group.values())
        else:
            conflict_patients = visit_result.dose_conflict_patients_by_group.get(
                group, 0
            )
            conflict_visits = visit_result.dose_conflict_visits_by_group.get(group, 0)
            conflict_items = visit_result.dose_conflict_items_by_group.get(group, 0)
        reportable = (
            conflict_patients == 0 or conflict_patients >= min_public_n
        ) and group not in suppressed_groups and not (
            group == "all" and suppressed_groups
        )
        rows.append(
            {
                "group": group,
                "patients": patients,
                "visits": visits,
                "patients_with_conflict": conflict_patients if reportable else None,
                "visits_with_conflict": conflict_visits if reportable else None,
                "visit_item_conflicts": conflict_items if reportable else None,
                "patients_with_conflict_pct": (
                    100 * conflict_patients / patients
                    if reportable and patients
                    else None
                ),
                "visits_with_conflict_pct": (
                    100 * conflict_visits / visits if reportable and visits else None
                ),
            }
        )
    return rows


def analyze(visit_result: VisitBuildResult, config: AnalysisConfig) -> AnalysisResult:
    visits_by_patient = visit_result.visits_by_patient
    group_names = tuple(group.name for group in config.groups)
    first_visits = _first_visits(visits_by_patient)
    counts, prevalence, denominators = _prevalence(first_visits, group_names)
    first_rows, suppressed = _first_prescription_rows(
        counts, prevalence, denominators, first_visits, config.min_public_n
    )
    longitudinal_rows, mode_rows = _longitudinal_rows(visits_by_patient, group_names)
    longitudinal_item_change_rows = _longitudinal_item_change_rows(
        visits_by_patient, group_names, config.min_public_n
    )
    temporal_cutpoint_rows, temporal_warnings = _temporal_rows(
        first_visits, config, config.temporal_cutpoints
    )
    temporal_rows = [
        row
        for row in temporal_cutpoint_rows
        if row["early_end_year"] == config.early_end_year
    ]
    (
        matched_rows,
        matched_sensitivity_rows,
        matched_metadata,
        matched_warnings,
    ) = _matched_reference_rows(visits_by_patient, config)
    combination_rows, combination_metadata, combination_warnings = (
        _frequent_combination_rows(first_visits, config)
    )
    (
        network_node_rows,
        network_edge_rows,
        network_sensitivity_rows,
        network_group_overlap_rows,
        network_membership_rows,
        network_metadata,
        network_warnings,
    ) = _network_rows(first_visits, config)

    return AnalysisResult(
        tables={
            "cohort_summary": _cohort_summary(visits_by_patient, group_names),
            "first_prescription_item_prevalence": first_rows,
            "frequent_item_combinations": combination_rows,
            "network_nodes": network_node_rows,
            "network_edges": network_edge_rows,
            "network_threshold_sensitivity": network_sensitivity_rows,
            "network_group_overlap": network_group_overlap_rows,
            "network_membership": network_membership_rows,
            "longitudinal_summary": longitudinal_rows,
            "transition_mode_summary": mode_rows,
            "longitudinal_item_change_tendency": longitudinal_item_change_rows,
            "cross_group_similarity": _cross_group_rows(
                group_names, counts, prevalence, config.min_public_n
            ),
            "temporal_stability": temporal_rows,
            "temporal_cutpoint_sensitivity": temporal_cutpoint_rows,
            "matched_reference_summary": matched_rows,
            "matched_reference_sensitivity": matched_sensitivity_rows,
            "item_normalization_audit": _item_normalization_rows(
                visit_result, config
            ),
            "dose_conflict_audit": _dose_conflict_rows(
                visit_result, group_names, config.min_public_n
            ),
        },
        metadata={
            "assigned_patients_with_visits": len(visits_by_patient),
            "suppressed_item_cells": suppressed,
            "item_normalization": {
                "version": config.item_normalization.version,
                "dictionary_entries": len(config.item_normalization.mappings),
                "changed_item_lines": visit_result.changed_item_line_count,
            },
            "dose_conflicts": {
                "visit_item_cells": visit_result.dose_conflict_item_count,
                "affected_patients": sum(
                    visit_result.dose_conflict_patients_by_group.values()
                ),
                "affected_visits": sum(
                    visit_result.dose_conflict_visits_by_group.values()
                ),
            },
            "matched_reference": matched_metadata,
            "combination_analysis": combination_metadata,
            "network_analysis": network_metadata,
        },
        warnings=tuple(
            [
                *temporal_warnings,
                *matched_warnings,
                *combination_warnings,
                *network_warnings,
            ]
        ),
    )
