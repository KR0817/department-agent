"""Patient-equal, descriptive sensitivity to adjacent eligible-visit gaps."""
from __future__ import annotations

import random
import statistics
from collections import defaultdict

from .analysis import PrescriptionVisit, _bootstrap_median, transition_metrics


WINDOWS = (("positive_gap", None), ("days_1_30", 30), ("days_1_90", 90), ("days_1_180", 180))


def visit_gap_sensitivity(
    visits_by_patient: dict[str, tuple[PrescriptionVisit, ...]],
    min_public_n: int,
    bootstrap_replicates: int = 1000,
    seed: int = 20260909,
) -> list[dict[str, object]]:
    """Retain original adjacencies; summarize within patients before groups.

    Nested patient denominators receive family-level complementary suppression.
    Same-day transitions are excluded only from this secondary analysis.
    """
    if min_public_n < 1 or bootstrap_replicates < 1:
        raise ValueError("Positive threshold and bootstrap count required")
    groups: dict[str, list[tuple[PrescriptionVisit, ...]]] = defaultdict(list)
    for visits in visits_by_patient.values():
        if not visits:
            continue
        if any(v.group != visits[0].group for v in visits):
            raise ValueError("Inconsistent patient group")
        if any(b.visit_date < a.visit_date for a, b in zip(visits, visits[1:])):
            raise ValueError("Visits must be ordered")
        groups[visits[0].group].append(visits)
    rows = []
    for group, histories in sorted(groups.items()):
        samples = []
        for _, limit in WINDOWS:
            patient_values = []
            for visits in histories:
                eligible = [(a, b, (b.visit_date - a.visit_date).days)
                            for a, b in zip(visits, visits[1:])
                            if (b.visit_date - a.visit_date).days > 0
                            and (limit is None or (b.visit_date - a.visit_date).days <= limit)]
                if eligible:
                    patient_values.append((
                        statistics.median(transition_metrics(a, b).jaccard for a, b, _ in eligible),
                        statistics.median(gap for _, _, gap in eligible),
                        (visits[-1].visit_date - visits[0].visit_date).days,
                        len(visits),
                    ))
            samples.append(patient_values)
        counts = [len(values) for values in samples]
        suppressed = any(n < min_public_n for n in counts) or any(
            0 < abs(left - right) < min_public_n for left in counts for right in counts
        )
        for index, ((window, _), values) in enumerate(zip(WINDOWS, samples)):
            row = dict.fromkeys(("patients", "median_patient_jaccard", "ci95_low", "ci95_high",
                                 "median_patient_gap_days", "median_history_days", "median_history_visits"), "")
            row.update(group=group, window=window, disclosure="SUPPRESSED_FAMILY" if suppressed else "PUBLIC")
            if not suppressed:
                jaccards = [value[0] for value in values]
                low, high = _bootstrap_median(jaccards, bootstrap_replicates, random.Random(seed + index))
                row.update(patients=len(values), median_patient_jaccard=statistics.median(jaccards),
                           ci95_low=low, ci95_high=high,
                           median_patient_gap_days=statistics.median(v[1] for v in values),
                           median_history_days=statistics.median(v[2] for v in values),
                           median_history_visits=statistics.median(v[3] for v in values))
            rows.append(row)
    return rows
