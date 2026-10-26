"""Public all-visit medication frequencies for consistent selector ordering."""
from collections import Counter

from .analysis import PrescriptionVisit


def item_usage_totals(
    visits_by_patient: dict[str, tuple[PrescriptionVisit, ...]], min_public_n: int
) -> list[dict[str, object]]:
    """Count normalized visit-item presence; suppress low patient support."""
    if min_public_n < 1:
        raise ValueError("min_public_n must be positive")
    totals: Counter[str] = Counter()
    patients: Counter[str] = Counter()
    for visits in visits_by_patient.values():
        seen = set()
        for visit in visits:
            totals.update(visit.items)
            seen.update(visit.items)
        patients.update(seen)
    return [
        {"item_name": item, "total_usage_visits": count}
        for item, count in sorted(totals.items(), key=lambda row: (-row[1], row[0]))
        if patients[item] >= min_public_n
    ]
