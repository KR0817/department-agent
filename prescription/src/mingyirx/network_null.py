"""Exploratory fixed-margin co-prescription background, separate from primary graphs."""
from __future__ import annotations

import itertools
import math
import random
import statistics
from collections import Counter

from .analysis import _bh_adjust, _network_setting


def trade(rows: list[set[str]], rng: random.Random) -> bool:
    """Uniformly redistribute exclusive items between two uniformly chosen rows."""
    if len(rows) < 2:
        return False
    left, right = rng.sample(range(len(rows)), 2)
    a, b = rows[left], rows[right]
    common = a & b
    pool = sorted(a ^ b)
    if not pool or not (a - b) or not (b - a):
        return False
    rng.shuffle(pool)
    split = len(a - common)
    new_a, new_b = common | set(pool[:split]), common | set(pool[split:])
    changed = new_a != a
    rows[left], rows[right] = new_a, new_b
    return changed


def _pair_counts(rows: list[set[str]], nodes: set[str]) -> Counter:
    result = Counter()
    for row in rows:
        result.update(itertools.combinations(sorted(row & nodes), 2))
    return result


def _diagnostics(chains: list[list[list[int]]]) -> tuple[float, float, float]:
    """Classical between-chain diagnostic plus within-chain lag correlation."""
    max_rhat, max_lag, max_delta = 1.0, 0.0, 0.0
    for index in range(len(chains[0][0])):
        series = [[row[index] for row in chain] for chain in chains]
        means = [statistics.mean(values) for values in series]
        within = statistics.mean(statistics.variance(values) for values in series)
        n = len(series[0])
        delta = abs(means[0] - means[1])
        max_delta = max(max_delta, delta)
        if within:
            between = n * statistics.variance(means)
            rhat = math.sqrt(((n-1)/n*within + between/n)/within)
            max_rhat = max(max_rhat, rhat)
        elif delta:
            max_rhat = math.inf
        for values, mean in zip(series, means):
            denominator = sum((v-mean)**2 for v in values)
            if denominator:
                lag = sum((a-mean)*(b-mean) for a,b in zip(values, values[1:])) / denominator
                max_lag = max(max_lag, abs(lag))
    return max_rhat, max_lag, max_delta


def fixed_margin_network(
    prescriptions: list[set[str]], group: str, min_public_n: int,
    node_prevalence: float, stability_probability: float, primary_cosine: float,
    seed: int = 20260909, draws_per_chain: int = 500,
    burn_sweeps: int = 20, thin_sweeps: int = 2,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """BH-adjust the complete fixed-node family before disclosing supported pairs."""
    if min_public_n < 1 or draws_per_chain < 3 or burn_sweeps < 1 or thin_sweeps < 1:
        raise ValueError('Invalid fixed-margin sampling parameters')
    n = len(prescriptions)
    if n < max(2, min_public_n):
        return [], {'group':group, 'status':'SUPPRESSED_GROUP'}
    marginals = Counter(item for row in prescriptions for item in row)
    node_map, _ = _network_setting(n, marginals, Counter(), node_prevalence,
                                   primary_cosine, min_public_n, stability_probability)
    nodes = set(node_map)
    pairs = list(itertools.combinations(sorted(nodes), 2))
    if not pairs:
        return [], {'group':group, 'status':'NO_ELIGIBLE_PAIRS'}
    observed = _pair_counts(prescriptions, nodes)
    row_sizes = [len(row) for row in prescriptions]
    chains = []
    changed = attempted = 0
    for chain_index in range(2):
        rng = random.Random(seed + chain_index)
        rows = [set(row) for row in prescriptions]
        retained = []
        for sample in range(draws_per_chain):
            steps = n * (burn_sweeps + thin_sweeps if sample == 0 else thin_sweeps)
            for _ in range(steps):
                changed += trade(rows, rng)
            attempted += steps
            if [len(row) for row in rows] != row_sizes or Counter(item for row in rows for item in row) != marginals:
                raise AssertionError('Fixed-margin invariant failed')
            counts = _pair_counts(rows, nodes)
            retained.append([counts[pair] for pair in pairs])
        chains.append(retained)
    rhat, lag, delta = _diagnostics(chains)
    diagnostic_status = 'REVIEW_REQUIRED' if rhat > 1.05 or lag > .2 else 'NO_FLAG_NOT_PROOF_OF_MIXING'
    all_draws = chains[0] + chains[1]
    probabilities, means = [], []
    for index, pair in enumerate(pairs):
        null = [sample[index] for sample in all_draws]
        probabilities.append((1 + sum(value >= observed[pair] for value in null))/(1+len(null)))
        means.append(statistics.mean(null))
    adjusted = _bh_adjust(probabilities)
    output = []
    for index, (left, right) in enumerate(pairs):
        count = observed[(left, right)]
        if count < min_public_n:
            continue
        cosine = count / math.sqrt(marginals[left]*marginals[right])
        output.append({'group':group, 'patients':n, 'item_1':left, 'item_2':right,
                       'observed_cooccurrence_patients':count, 'null_mean_cooccurrence':means[index],
                       'observed_minus_null':count-means[index], 'mc_upper_tail_p':probabilities[index],
                       'mc_bh_q':adjusted[index], 'primary_network_edge':cosine >= primary_cosine,
                       'family_pairs':len(pairs), 'retained_draws':len(all_draws),
                       'sampling_status':diagnostic_status})
    return output, {'group':group, 'status':diagnostic_status, 'patients':n,
                    'family_nodes':len(nodes), 'family_pairs':len(pairs),
                    'disclosed_pairs':len(output), 'seed':seed, 'draws_per_chain':draws_per_chain,
                    'burn_sweeps':burn_sweeps, 'thin_sweeps':thin_sweeps,
                    'changed_trade_fraction':changed/attempted, 'max_edge_rhat':rhat if math.isfinite(rhat) else None,
                    'max_abs_edge_lag1':lag, 'max_chain_mean_difference':delta,
                    'fixed_margins':'PASS', 'interpretation':'EXPLORATORY_MCMC_NOT_CLINICAL_SYNERGY'}
