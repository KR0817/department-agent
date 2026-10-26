"""Source comparison utilities with explicit independence and disclosure gates."""
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
import json

from .pipeline import validate_pipeline
from .io import file_sha256


def load_contexts(root: Path, manifest: Path | None = None):
    """Load explicitly configured sources; source keys do not imply care setting."""
    path = manifest or root/'work/source_contexts.json'
    definitions = json.loads(path.read_text(encoding='utf-8'))
    contexts = {}
    for label, definition in definitions.items():
        inputs = [Path(row['path']) for row in definition['inputs']]
        for row, source in zip(definition['inputs'], inputs):
            if file_sha256(source) != row['sha256']:
                raise ValueError('Frozen source input hash mismatch')
        contexts[label] = validate_pipeline(Path(definition['config']), inputs)
    return contexts


def select_histories(context, group='as_strict'):
    return {p:vs for p,vs in context.visit_result.visits_by_patient.items() if vs and vs[0].group==group}


def fingerprint(visit, include_dose=True):
    if include_dose:
        if not visit.dose_resolved:return None
        values=tuple(sorted((name,visit.doses[name]) for name in visit.items))
    else:values=tuple(sorted(visit.items))
    return visit.visit_date, values


def fingerprint_links(left, right, include_dose=True):
    indices=[]
    for histories in (left,right):
        index=defaultdict(list)
        for pid,visits in histories.items():
            for visit in visits:
                key=fingerprint(visit,include_dose)
                if key is not None:index[key].append((pid,visit.visit_id))
        indices.append(index)
    common=indices[0].keys() & indices[1].keys()
    pairs=defaultdict(set)
    for key in common:
        for lp,_ in indices[0][key]:
            for rp,_ in indices[1][key]:pairs[(lp,rp)].add(key[0])
    linked=[{pid for key in common for pid,_ in index[key]} for index in indices]
    counts={'matched_fingerprints':len(common),'outpatient_ids':len(linked[0]),'inpatient_ids':len(linked[1]),
        'candidate_pairs':len(pairs),'multiple_date_candidate_pairs':sum(len(ds)>=2 for ds in pairs.values()),
        'matched_outpatient_records':sum(len(indices[0][key]) for key in common),
        'matched_inpatient_records':sum(len(indices[1][key]) for key in common)}
    return counts,pairs


def observed_window(histories):
    values=[v.visit_date for vs in histories.values() for v in vs]
    return min(values),max(values)


def common_window(histories_by_source):
    bounds=[observed_window(h) for h in histories_by_source.values()]
    lower,upper=max(x[0] for x in bounds),min(x[1] for x in bounds)
    if lower>upper:raise ValueError('No overlapping calendar window')
    return lower,upper


def window_histories(histories,lower,upper):
    return {pid:tuple(v for v in vs if lower<=v.visit_date<=upper) for pid,vs in histories.items()
            if any(lower<=v.visit_date<=upper for v in vs)}


def adjacent_pairs(histories, lower, upper, max_gap, eligible_keys=None, original_adjacencies=None):
    """Filter original adjacencies; never reconnect around excluded records."""
    result={}
    for pid,visits in histories.items():
        pairs=[]
        for left,right in zip(visits,visits[1:]):
            if original_adjacencies is not None and (pid,left.visit_id,right.visit_id) not in original_adjacencies:continue
            gap=(right.visit_date-left.visit_date).days
            if not(lower<=left.visit_date<=upper and lower<=right.visit_date<=upper and 1<=gap<=max_gap):continue
            if eligible_keys is not None and ((pid,left.visit_id) not in eligible_keys or (pid,right.visit_id) not in eligible_keys):continue
            pairs.append((left,right,gap))
        if pairs:result[pid]=pairs
    return result


def supported_count(count,total=None,minimum=10):
    return (count==0 or count>=minimum) and (total is None or total-count==0 or total-count>=minimum)


def complementary_family(counts,minimum=10):
    return all(supported_count(n,minimum=minimum) for n in counts) and not any(0<abs(a-b)<minimum for a in counts for b in counts)


def original_adjacencies(context):
    events=defaultdict(dict)
    for row in context.read_result.records:events[row.patient_id][row.visit_id]=row.visit_date
    result=set()
    for pid,visits in events.items():
        order=sorted(visits,key=lambda k:(visits[k],k))
        result.update((pid,a,b) for a,b in zip(order,order[1:]))
    return result


def conditional_rates(pairs_by_patient, item, mode):
    """Patient-equal change fractions among the correct opportunity set."""
    fractions=[];opportunities=0;changes=0;changed_patients=0
    for pairs in pairs_by_patient.values():
        eligible=[(a,b) for a,b,_ in pairs if (item not in a.items if mode=='addition' else item in a.items)]
        if not eligible:continue
        n=sum(item in b.items if mode=='addition' else item not in b.items for a,b in eligible)
        fractions.append(n/len(eligible));opportunities+=len(eligible);changes+=n;changed_patients+=n>0
    return {'patients':len(fractions),'changed_patients':changed_patients,'opportunities':opportunities,'changes':changes,
            'mean_patient_rate':sum(fractions)/len(fractions) if fractions else None}
