from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the analysis configuration is incomplete or unsafe."""


REQUIRED_COLUMNS = {
    "patient_id",
    "visit_id",
    "visit_date",
    "diagnosis_text",
    "item_name",
}

ColumnSelector = str | int


@dataclass(frozen=True)
class GroupRule:
    name: str
    label: str
    include_patterns: tuple[str, ...]
    exclude_patterns: tuple[str, ...]


@dataclass(frozen=True)
class ItemEligibility:
    allowed_units: tuple[str, ...]
    excluded_exact_names: tuple[str, ...]
    excluded_name_patterns: tuple[str, ...]


@dataclass(frozen=True)
class ItemNormalizationConfig:
    version: str
    dictionary_path: Path | None
    dictionary_sha256: str | None
    mappings: dict[str, str]


@dataclass(frozen=True)
class MatchedReferenceConfig:
    enabled: bool
    assume_single_physician: bool
    random_seed: int
    bootstrap_replicates: int
    null_replicates: int


@dataclass(frozen=True)
class CombinationAnalysisConfig:
    enabled: bool
    sizes: tuple[int, ...]
    stability_probability: float


@dataclass(frozen=True)
class NetworkAnalysisConfig:
    enabled: bool
    primary_cosine: float
    node_prevalence_thresholds: tuple[float, ...]
    edge_cosine_thresholds: tuple[float, ...]
    stability_probability: float


@dataclass(frozen=True)
class AgeBand:
    name: str
    label: str
    min_age: int
    max_age: int


@dataclass(frozen=True)
class ClinicalPhenotypeAnalysisConfig:
    enabled: bool
    other_exclude_patterns: tuple[str, ...]
    sex_value_to_category: dict[str, str]
    sex_labels: dict[str, str]
    age_bands: tuple[AgeBand, ...]


@dataclass(frozen=True)
class AnalysisConfig:
    project_id: str
    dataset_id: str
    cohort_version: str
    encoding: str
    columns: dict[str, ColumnSelector]
    groups: tuple[GroupRule, ...]
    exclusive_groups: bool
    min_public_n: int
    synthetic_mode: bool
    date_formats: tuple[str, ...]
    early_end_year: int
    temporal_cutpoints: tuple[int, ...]
    core_prevalence: float
    cross_file_overlap_policy: str
    expected_input_sha256: dict[str, str]
    require_visit_group_match: bool
    item_eligibility: ItemEligibility
    item_normalization: ItemNormalizationConfig
    matched_reference: MatchedReferenceConfig
    combination_analysis: CombinationAnalysisConfig
    network_analysis: NetworkAnalysisConfig
    clinical_phenotype_analysis: ClinicalPhenotypeAnalysisConfig


def _required_string(data: dict[str, Any], key: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise ConfigError(f"Missing required configuration value: {key}")
    return value


def _string_list(value: Any, key: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{key} must be a JSON list")
    values = tuple(str(item).strip() for item in value if str(item).strip())
    if not values and not allow_empty:
        raise ConfigError(f"{key} must contain at least one value")
    return values


def _column_selector(value: Any, key: str) -> ColumnSelector:
    if isinstance(value, bool):
        raise ConfigError(f"{key} must be a header string or zero-based integer position")
    if isinstance(value, int):
        if value < 0:
            raise ConfigError(f"{key} position cannot be negative")
        return value
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ConfigError(f"{key} must be a nonblank header string or zero-based integer position")


def _probability_list(value: Any, key: str) -> tuple[float, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        raise ConfigError(f"{key} must be a non-empty numeric JSON list")
    values = tuple(float(item) for item in value)
    if values != tuple(sorted(set(values))):
        raise ConfigError(f"{key} must contain unique values in ascending order")
    if any(not 0 < item <= 1 for item in values):
        raise ConfigError(f"{key} values must be in (0, 1]")
    return values


def _normalize_dictionary_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.replace("\u3000", " ").split())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_item_normalization(
    raw: dict[str, Any], config_path: Path, synthetic_mode: bool
) -> ItemNormalizationConfig:
    normalization_raw = raw.get(
        "item_normalization",
        {"version": "source-string-v1", "dictionary_path": None},
    )
    if not isinstance(normalization_raw, dict):
        raise ConfigError("item_normalization must be a JSON object")
    version = _required_string(normalization_raw, "version")
    path_value = normalization_raw.get("dictionary_path")
    expected_value = normalization_raw.get("expected_sha256")
    if path_value is None or path_value == "":
        if expected_value is not None and expected_value != "":
            raise ConfigError(
                "item_normalization.expected_sha256 requires dictionary_path"
            )
        return ItemNormalizationConfig(
            version=version,
            dictionary_path=None,
            dictionary_sha256=None,
            mappings={},
        )

    dictionary_path = Path(str(path_value))
    if not dictionary_path.is_absolute():
        dictionary_path = config_path.resolve().parent / dictionary_path
    dictionary_path = dictionary_path.resolve()
    if not dictionary_path.is_file():
        raise ConfigError("item_normalization.dictionary_path is not a file")

    dictionary_sha256 = _file_sha256(dictionary_path)
    expected_sha256 = str(expected_value or "").strip().lower()
    if expected_sha256 and not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ConfigError(
            "item_normalization.expected_sha256 must be a SHA-256 hex digest"
        )
    if not synthetic_mode and not expected_sha256:
        raise ConfigError("Real-data item dictionaries require expected_sha256")
    if expected_sha256 and dictionary_sha256 != expected_sha256:
        raise ConfigError("Item dictionary SHA-256 does not match expected_sha256")

    mappings: dict[str, str] = {}
    with dictionary_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"source_item_name", "canonical_item_name"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ConfigError(
                "Item dictionary requires source_item_name and canonical_item_name"
            )
        for row_number, row in enumerate(reader, start=2):
            source = _normalize_dictionary_name(row["source_item_name"])
            canonical = _normalize_dictionary_name(row["canonical_item_name"])
            if not source or not canonical:
                raise ConfigError(f"Item dictionary row {row_number} contains a blank name")
            if source in mappings:
                raise ConfigError("Item dictionary contains a duplicate source_item_name")
            mappings[source] = canonical
    if not mappings:
        raise ConfigError("Item dictionary must contain at least one mapping")
    if any(
        canonical in mappings
        and canonical != source
        and mappings[canonical] != canonical
        for source, canonical in mappings.items()
    ):
        raise ConfigError("Item dictionary mappings must be direct, not chained")
    return ItemNormalizationConfig(
        version=version,
        dictionary_path=dictionary_path,
        dictionary_sha256=dictionary_sha256,
        mappings=mappings,
    )


def load_config(path: Path) -> AnalysisConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("Configuration root must be a JSON object")

    columns = raw.get("columns")
    if not isinstance(columns, dict):
        raise ConfigError("columns must be a JSON object")
    columns = {
        str(key): _column_selector(value, f"columns.{key}")
        for key, value in columns.items()
    }
    missing_columns = sorted(REQUIRED_COLUMNS - columns.keys())
    if missing_columns:
        raise ConfigError(f"Missing canonical column mappings: {', '.join(missing_columns)}")

    cross_file_overlap_policy = str(
        raw.get("cross_file_overlap_policy", "append")
    ).strip()
    if cross_file_overlap_policy not in {"append", "max_multiplicity"}:
        raise ConfigError(
            "cross_file_overlap_policy must be 'append' or 'max_multiplicity'"
        )

    expected_hashes_raw = raw.get("expected_input_sha256", {})
    if not isinstance(expected_hashes_raw, dict):
        raise ConfigError("expected_input_sha256 must be a JSON object")
    expected_input_sha256: dict[str, str] = {}
    for filename, digest in expected_hashes_raw.items():
        normalized_filename = str(filename).strip()
        normalized_digest = str(digest).strip().lower()
        if not normalized_filename:
            raise ConfigError("expected_input_sha256 filenames cannot be blank")
        if not re.fullmatch(r"[0-9a-f]{64}", normalized_digest):
            raise ConfigError(
                f"expected_input_sha256[{normalized_filename!r}] must be a SHA-256 hex digest"
            )
        expected_input_sha256[normalized_filename] = normalized_digest

    item_eligibility_raw = raw.get("item_eligibility", {})
    if not isinstance(item_eligibility_raw, dict):
        raise ConfigError("item_eligibility must be a JSON object")
    allowed_units = _string_list(
        item_eligibility_raw.get("allowed_units", []),
        "item_eligibility.allowed_units",
        allow_empty=True,
    )
    excluded_exact_names = _string_list(
        item_eligibility_raw.get("excluded_exact_names", []),
        "item_eligibility.excluded_exact_names",
        allow_empty=True,
    )
    excluded_name_patterns = _string_list(
        item_eligibility_raw.get("excluded_name_patterns", []),
        "item_eligibility.excluded_name_patterns",
        allow_empty=True,
    )
    for pattern in excluded_name_patterns:
        try:
            re.compile(pattern, flags=re.IGNORECASE)
        except re.error as error:
            raise ConfigError(f"Invalid item eligibility regular expression: {error}") from error

    group_rows = raw.get("groups")
    if not isinstance(group_rows, list) or len(group_rows) < 2:
        raise ConfigError("groups must contain at least two group rules")
    groups: list[GroupRule] = []
    seen_names: set[str] = set()
    for index, group in enumerate(group_rows):
        if not isinstance(group, dict):
            raise ConfigError(f"groups[{index}] must be a JSON object")
        name = _required_string(group, "name")
        if name in seen_names:
            raise ConfigError(f"Duplicate group name: {name}")
        seen_names.add(name)
        include_patterns = _string_list(group.get("include_patterns"), f"groups[{index}].include_patterns")
        exclude_patterns = _string_list(
            group.get("exclude_patterns", []),
            f"groups[{index}].exclude_patterns",
            allow_empty=True,
        )
        for pattern in (*include_patterns, *exclude_patterns):
            try:
                re.compile(pattern, flags=re.IGNORECASE)
            except re.error as error:
                raise ConfigError(f"Invalid regular expression for group {name}: {error}") from error
        groups.append(
            GroupRule(
                name=name,
                label=str(group.get("label", name)).strip() or name,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
            )
        )

    exclusive_groups = bool(raw.get("exclusive_groups", True))
    if not exclusive_groups:
        raise ConfigError("Version 0.1 supports exclusive_groups=true only")

    min_public_n = int(raw.get("min_public_n", 10))
    synthetic_mode = raw.get("synthetic_mode", False)
    if not isinstance(synthetic_mode, bool):
        raise ConfigError("synthetic_mode must be a JSON boolean")
    if min_public_n < 1:
        raise ConfigError("min_public_n must be positive")
    if min_public_n < 10 and not synthetic_mode:
        raise ConfigError("min_public_n below 10 is allowed only when synthetic_mode=true")
    item_normalization = _load_item_normalization(raw, path, synthetic_mode)

    matched_raw = raw.get("matched_reference", {})
    if not isinstance(matched_raw, dict):
        raise ConfigError("matched_reference must be a JSON object")
    matched_reference = MatchedReferenceConfig(
        enabled=bool(matched_raw.get("enabled", False)),
        assume_single_physician=bool(
            matched_raw.get("assume_single_physician", False)
        ),
        random_seed=int(matched_raw.get("random_seed", 20260822)),
        bootstrap_replicates=int(matched_raw.get("bootstrap_replicates", 1000)),
        null_replicates=int(matched_raw.get("null_replicates", 1000)),
    )
    if matched_reference.random_seed < 0:
        raise ConfigError("matched_reference.random_seed cannot be negative")
    if matched_reference.bootstrap_replicates < 1:
        raise ConfigError("matched_reference.bootstrap_replicates must be positive")
    if matched_reference.null_replicates < 1:
        raise ConfigError("matched_reference.null_replicates must be positive")
    if matched_reference.enabled and not synthetic_mode:
        if matched_reference.bootstrap_replicates < 1000:
            raise ConfigError(
                "Real-data matched_reference.bootstrap_replicates must be at least 1000"
            )
        if matched_reference.null_replicates < 1000:
            raise ConfigError(
                "Real-data matched_reference.null_replicates must be at least 1000"
            )

    combination_raw = raw.get("combination_analysis", {})
    if not isinstance(combination_raw, dict):
        raise ConfigError("combination_analysis must be a JSON object")
    combination_sizes_raw = combination_raw.get("sizes", [2, 3])
    if (
        not isinstance(combination_sizes_raw, list)
        or not combination_sizes_raw
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in combination_sizes_raw
        )
    ):
        raise ConfigError("combination_analysis.sizes must be a non-empty integer list")
    combination_sizes = tuple(combination_sizes_raw)
    if combination_sizes != tuple(sorted(set(combination_sizes))):
        raise ConfigError(
            "combination_analysis.sizes must contain unique values in ascending order"
        )
    if any(size not in {2, 3} for size in combination_sizes):
        raise ConfigError("combination_analysis.sizes supports only 2 and 3")
    combination_stability_probability = float(
        combination_raw.get("stability_probability", 0.80)
    )
    if not 0 < combination_stability_probability <= 1:
        raise ConfigError(
            "combination_analysis.stability_probability must be in (0, 1]"
        )
    combination_analysis = CombinationAnalysisConfig(
        enabled=bool(combination_raw.get("enabled", False)),
        sizes=combination_sizes,
        stability_probability=combination_stability_probability,
    )

    date_formats = _string_list(
        raw.get("date_formats", ["%Y-%m-%d", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"]),
        "date_formats",
    )
    early_end_year = int(raw.get("early_end_year", 2019))
    temporal_cutpoints_raw = raw.get("temporal_cutpoints", [early_end_year])
    if (
        not isinstance(temporal_cutpoints_raw, list)
        or not temporal_cutpoints_raw
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in temporal_cutpoints_raw
        )
    ):
        raise ConfigError("temporal_cutpoints must be a non-empty JSON integer list")
    temporal_cutpoints = tuple(temporal_cutpoints_raw)
    if len(set(temporal_cutpoints)) != len(temporal_cutpoints):
        raise ConfigError("temporal_cutpoints cannot contain duplicates")
    if temporal_cutpoints != tuple(sorted(temporal_cutpoints)):
        raise ConfigError("temporal_cutpoints must be in ascending order")
    if early_end_year not in temporal_cutpoints:
        raise ConfigError("temporal_cutpoints must include early_end_year")
    core_prevalence = float(raw.get("core_prevalence", 0.20))
    if not 0 < core_prevalence <= 1:
        raise ConfigError("core_prevalence must be in (0, 1]")

    network_raw = raw.get("network_analysis", {})
    if not isinstance(network_raw, dict):
        raise ConfigError("network_analysis must be a JSON object")
    primary_cosine = float(network_raw.get("primary_cosine", 0.50))
    if not 0 < primary_cosine <= 1:
        raise ConfigError("network_analysis.primary_cosine must be in (0, 1]")
    node_prevalence_thresholds = _probability_list(
        network_raw.get("node_prevalence_thresholds", [core_prevalence]),
        "network_analysis.node_prevalence_thresholds",
    )
    edge_cosine_thresholds = _probability_list(
        network_raw.get("edge_cosine_thresholds", [primary_cosine]),
        "network_analysis.edge_cosine_thresholds",
    )
    if core_prevalence not in node_prevalence_thresholds:
        raise ConfigError(
            "network_analysis.node_prevalence_thresholds must include core_prevalence"
        )
    if primary_cosine not in edge_cosine_thresholds:
        raise ConfigError(
            "network_analysis.edge_cosine_thresholds must include primary_cosine"
        )
    network_stability_probability = float(
        network_raw.get(
            "stability_probability",
            combination_analysis.stability_probability,
        )
    )
    if not 0 < network_stability_probability <= 1:
        raise ConfigError(
            "network_analysis.stability_probability must be in (0, 1]"
        )
    network_analysis = NetworkAnalysisConfig(
        enabled=bool(network_raw.get("enabled", False)),
        primary_cosine=primary_cosine,
        node_prevalence_thresholds=node_prevalence_thresholds,
        edge_cosine_thresholds=edge_cosine_thresholds,
        stability_probability=network_stability_probability,
    )

    clinical_raw = raw.get("clinical_phenotype_analysis", {})
    if not isinstance(clinical_raw, dict):
        raise ConfigError("clinical_phenotype_analysis must be a JSON object")
    clinical_enabled = bool(clinical_raw.get("enabled", False))
    other_exclude_patterns = _string_list(
        clinical_raw.get("other_exclude_patterns", []),
        "clinical_phenotype_analysis.other_exclude_patterns",
        allow_empty=True,
    )
    for pattern in other_exclude_patterns:
        try:
            re.compile(pattern, flags=re.IGNORECASE)
        except re.error as error:
            raise ConfigError(
                f"Invalid clinical phenotype exclusion regular expression: {error}"
            ) from error

    sex_rows = clinical_raw.get("sex_categories", [])
    if not isinstance(sex_rows, list):
        raise ConfigError("clinical_phenotype_analysis.sex_categories must be a list")
    sex_value_to_category: dict[str, str] = {}
    sex_labels: dict[str, str] = {}
    for index, row in enumerate(sex_rows):
        if not isinstance(row, dict):
            raise ConfigError(
                f"clinical_phenotype_analysis.sex_categories[{index}] must be an object"
            )
        name = _required_string(row, "name")
        if name in sex_labels:
            raise ConfigError(f"Duplicate clinical sex category: {name}")
        label = str(row.get("label", name)).strip() or name
        source_values = _string_list(
            row.get("source_values"),
            f"clinical_phenotype_analysis.sex_categories[{index}].source_values",
        )
        sex_labels[name] = label
        for value in source_values:
            normalized = _normalize_dictionary_name(value).casefold()
            if normalized in sex_value_to_category:
                raise ConfigError(f"Duplicate clinical sex source value: {value}")
            sex_value_to_category[normalized] = name

    age_rows = clinical_raw.get("age_bands", [])
    if not isinstance(age_rows, list):
        raise ConfigError("clinical_phenotype_analysis.age_bands must be a list")
    age_bands: list[AgeBand] = []
    seen_age_names: set[str] = set()
    for index, row in enumerate(age_rows):
        if not isinstance(row, dict):
            raise ConfigError(
                f"clinical_phenotype_analysis.age_bands[{index}] must be an object"
            )
        name = _required_string(row, "name")
        if name in seen_age_names:
            raise ConfigError(f"Duplicate clinical age band: {name}")
        seen_age_names.add(name)
        min_age = int(row.get("min_age", 0))
        max_age = int(row.get("max_age", 120))
        if min_age < 0 or max_age > 130 or min_age > max_age:
            raise ConfigError(
                f"clinical_phenotype_analysis.age_bands[{index}] has invalid bounds"
            )
        age_bands.append(
            AgeBand(
                name=name,
                label=str(row.get("label", name)).strip() or name,
                min_age=min_age,
                max_age=max_age,
            )
        )
    age_bands.sort(key=lambda band: (band.min_age, band.max_age, band.name))
    for left, right in zip(age_bands, age_bands[1:]):
        if right.min_age <= left.max_age:
            raise ConfigError("clinical_phenotype_analysis.age_bands cannot overlap")
    if clinical_enabled:
        missing_demographic_columns = {"sex", "birth_date"} - columns.keys()
        if missing_demographic_columns:
            raise ConfigError(
                "Enabled clinical phenotype analysis requires column mappings: "
                + ", ".join(sorted(missing_demographic_columns))
            )
        if not sex_value_to_category or not age_bands:
            raise ConfigError(
                "Enabled clinical phenotype analysis requires sex categories and age bands"
            )
    clinical_phenotype_analysis = ClinicalPhenotypeAnalysisConfig(
        enabled=clinical_enabled,
        other_exclude_patterns=other_exclude_patterns,
        sex_value_to_category=sex_value_to_category,
        sex_labels=sex_labels,
        age_bands=tuple(age_bands),
    )

    return AnalysisConfig(
        project_id=_required_string(raw, "project_id"),
        dataset_id=_required_string(raw, "dataset_id"),
        cohort_version=_required_string(raw, "cohort_version"),
        encoding=str(raw.get("encoding", "utf-8-sig")),
        columns=columns,
        groups=tuple(groups),
        exclusive_groups=exclusive_groups,
        min_public_n=min_public_n,
        synthetic_mode=synthetic_mode,
        date_formats=date_formats,
        early_end_year=early_end_year,
        temporal_cutpoints=temporal_cutpoints,
        core_prevalence=core_prevalence,
        cross_file_overlap_policy=cross_file_overlap_policy,
        expected_input_sha256=expected_input_sha256,
        require_visit_group_match=bool(raw.get("require_visit_group_match", False)),
        item_eligibility=ItemEligibility(
            allowed_units=allowed_units,
            excluded_exact_names=excluded_exact_names,
            excluded_name_patterns=excluded_name_patterns,
        ),
        item_normalization=item_normalization,
        matched_reference=matched_reference,
        combination_analysis=combination_analysis,
        network_analysis=network_analysis,
        clinical_phenotype_analysis=clinical_phenotype_analysis,
    )
