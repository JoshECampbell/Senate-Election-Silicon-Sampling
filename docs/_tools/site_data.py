"""Prepare an offline website snapshot from saved query and validation tables.

Nothing here queries a model or modifies analysis inputs. Recompute state means
from valid sampled rows, reconcile them with the saved summaries, and preserve
all draw positions for the figures. Costs come from attempt records, never from
expanded persona rows. Discovery uses dated run folders and an explicit study condition; incomplete
model-days do not prevent the other models from publishing.
"""

from collections import Counter
from datetime import datetime, date
import json
import math
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import yaml

from src.helper_query_validation import probability_error


CATEGORIES = [
    ("p_democrat", "Democrat", "#326A9D"),
    ("p_republican", "Republican", "#BD4942"),
    ("p_third_party", "Third party / independent", "#777777"),
    ("p_would_not_vote", "Would not vote", "#C7C7C3"),
]
FEATURE_NAMES = {"age": "Age", "race": "Race", "pid7": "Party identification",
                 "sexuality": "Sexual orientation", "educ": "Education"}
SEAT_CATEGORIES = [
    ("democrat", "Democratic seats", "p_democrat", "#326A9D"),
    ("republican", "Republican seats", "p_republican", "#BD4942"),
    ("independent", "Independent / other seats", "p_third_party", "#777777"),
]


def headline_outcome(totals):
    """Describe party seats without assigning independents to either caucus.

    A largest party is not necessarily a 51-seat majority. In particular,
    50 D / 48 R / 2 independent means a Democratic lead, not Republican control
    and not an outright Democratic majority.
    """
    if totals['democrat']>=51:
        return 'Democratic majority', '#326A9D'
    if totals['republican']>=51:
        return 'Republican majority', '#BD4942'
    if totals['democrat']>totals['republican']:
        return 'Democrats lead; no outright majority', '#326A9D'
    if totals['republican']>totals['democrat']:
        return 'Republicans lead; no outright majority', '#BD4942'
    return 'Parties tied; no outright majority', '#62615D'


def project_senate(leaders, baseline):
    """Add fixed seats to modeled race leaders; retain independent and tied seats.

    The baseline is supplied by the owner, not estimated by a model. Validate
    its 65 fixed seats, the 35 outcomes, and conservation of the 100-seat total.
    Tied/missing contests stay unallocated; they are not independent wins.
    """
    fixed = baseline["fixed_seats"]
    allowed = {category[2] for category in SEAT_CATEGORIES} | {"unallocated"}
    if set(fixed) != {category[0] for category in SEAT_CATEGORIES}:
        raise ValueError("The baseline must name Democrat, Republican, and independent seats.")
    counts = [*fixed.values(), *leaders.values(), baseline["chamber_seats"], baseline["contested_seats"]]
    if any(type(count) is not int or count < 0 for count in counts):
        raise ValueError("Seat counts must be nonnegative integers.")
    if set(leaders) - allowed:
        raise ValueError("Unexpected winner category; non-voting cannot win a Senate seat.")
    if baseline["chamber_seats"] != 100 or baseline["contested_seats"] != 35 or sum(fixed.values()) != 65:
        raise ValueError("This election requires 65 fixed seats plus 35 contests in a 100-seat chamber.")
    if sum(leaders.values()) != baseline["contested_seats"]:
        raise ValueError("Modeled leaders and unallocated races must total 35.")
    projected = {key: leaders.get(column, 0) for key, _, column, _ in SEAT_CATEGORIES}
    totals = {key: fixed[key] + projected[key] for key, _, _, _ in SEAT_CATEGORIES}
    totals["unallocated"] = leaders.get("unallocated", 0)
    if sum(totals.values()) != 100:
        raise ValueError("Full Senate totals do not reconcile to 100.")
    return {"baseline": baseline, "projected": projected, "totals": totals}


def slug(value):
    return value.lower().replace(" ", "-")


def reporting_date(name, timestamps, timezone):
    """Use ISO folder prefixes; accept legacy oct-26 names using timestamp year.

    Folder mtime is never a research date. A mismatch with the local collection
    date is rejected, rather than silently moving observations to another day.
    Non-dated folders (old probes/pilots) are not discovered.
    """
    local_dates = {datetime.fromisoformat(t).astimezone(ZoneInfo(timezone)).date()
                   for t in timestamps if t}
    if len(local_dates) != 1:
        raise ValueError("Collection must belong to one local reporting day.")
    actual = next(iter(local_dates))
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:-|_|$)", name)
    if match:
        declared = date.fromisoformat(match[1])
    else:
        match = re.match(r"^([a-z]{3})-(\d{1,2})(?:-|_|$)", name.lower())
        if not match:
            return None
        months = {m: i+1 for i, m in enumerate(
            ('jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'))}
        if match[1] not in months:
            return None
        declared = date(actual.year, months[match[1]], int(match[2]))
    if declared != actual:
        raise ValueError(f"Folder date {declared} differs from local collection date {actual}.")
    return declared.isoformat()


def validation_data(root, sample_name):
    """Load the existing CES checks once; retain all saved feature categories."""
    folder = root / 'data/persona_validation' / sample_name
    distributions = pl.read_parquet(folder / f'{sample_name}_distributions.parquet')
    metrics = pl.read_parquet(folder / f'{sample_name}_summary.parquet')
    labels = yaml.safe_load((root / 'config/ces_codes/ces25_value_labels.yaml').read_text(encoding='utf-8'))['variables']
    existing = set(distributions['feature'].unique())
    order = [f for f in FEATURE_NAMES if f in existing] + sorted(existing-set(FEATURE_NAMES))
    features = [{'key': f, 'name': FEATURE_NAMES.get(f, labels.get(f, {}).get('description', f))} for f in order]
    states = {}
    samples = {}
    for file in sorted((root / 'data/personas' / sample_name).glob('*.parquet')):
        name = file.stem
        samples[name] = pl.read_parquet(file)['caseid'].to_list()
        values = {}
        for f in order:
            data = distributions.filter((pl.col('state')==name) & (pl.col('feature')==f)).sort('category_order')
            if data.is_empty() or data['persona_total_count'].unique().to_list() != [100]:
                raise ValueError(f'{name}/{f}: missing or mismatched persona validation.')
            metric = metrics.filter((pl.col('state')==name) & (pl.col('feature')==f)).row(0,named=True)
            values[f] = {'categories': data.to_dicts(), 'tv': metric['total_variation_distance'],
                         'max_gap_pp': metric['max_absolute_difference_pp']}
        states[slug(name)] = {'name': name, 'validation': values}
    if len(states) != 35:
        raise ValueError('Expected 35 source state samples.')
    return states, samples, features


def state_result(rows, sample_ids, saved_summary):
    """Publish only the original complete draw sample and a reconciled summary.

    Any failed/missing/duplicate row makes this state/model/day unavailable.
    Other state/model/days remain usable. Never reweight or replace failed rows.
    """
    columns = [c[0] for c in CATEGORIES]
    valid = [r for r in rows if probability_error(r, columns) is None]
    result = {'draws': 100, 'observed': len(rows), 'valid': len(valid),
              'unique': len({r['caseid'] for r in rows}), 'eligible': False,
              'means': None, 'points': [], 'reason': None}
    if len(rows) != 100 or len(sample_ids) != 100 or [r['persona_row'] for r in rows] != list(range(100)):
        result['reason'] = 'Missing or duplicate sampled rows; expected positions 0–99.'
    elif [r['caseid'] for r in rows] != sample_ids:
        result['reason'] = 'Response IDs differ from the configured persona sample.'
    elif len(valid) != 100:
        result['reason'] = f'Only {len(valid)}/100 sampled responses are valid.'
    elif len(saved_summary) != 1:
        result['reason'] = 'Missing or ambiguous saved state summary.'
    else:
        means = {c: math.fsum(r[c] for r in valid)/100 for c in columns}
        saved = saved_summary[0]
        if any(saved.get(c) is None or not math.isfinite(saved[c]) or abs(means[c]-saved[c])>1e-12 for c in columns):
            result['reason'] = 'Saved summary does not match independently recomputed draw means.'
        else:
            voting = max(means[c] for c in columns[:3])
            winners = [c for c in columns[:3] if abs(means[c]-voting)<=1e-12]
            result.update(eligible=True, means=means, leader=winners[0] if len(winners)==1 else 'unallocated',
                          points=[{'draw': r['persona_row']+1, **{c:r[c] for c in columns}} for r in valid])
    return result


def choose_candidate(candidates):
    """Prefer a complete model-day, then the most recent collection, never pool runs."""
    return max(candidates, key=lambda c: (c['complete'], c['collected_at'], c['run']))


USAGE_FIELDS = (('known_cost','unknown_costs'),
                ('input_tokens','unknown_input_tokens'),
                ('output_tokens','unknown_output_tokens'))


def request_usage(attempts, model_rows):
    """Sum logged attempts, or distinct latest responses if logs are unavailable.

    Expanded persona rows are never separate API usage. JSONL includes retries;
    Parquet only retains latest responses, so its fallback is a partial total.
    Preserve missing fields as unknown. Output tokens are usually available only
    inside the raw response usage object, not the current results Parquet schema.
    """
    latest_rows=model_rows
    if 'status' in latest_rows.columns:
        latest_rows=latest_rows.filter(pl.col('status')!='not_queried')
    records = attempts if attempts else latest_rows.unique(subset=['state','caseid']).to_dicts()
    result={'attempts':len(records),'partial':not bool(attempts),
            'source':'attempt_log' if attempts else 'latest_results'}
    names={'known_cost':('cost_usd','cost'), 'input_tokens':('input_tokens','prompt_tokens'),
           'output_tokens':('output_tokens','completion_tokens')}
    for field,unknown in USAGE_FIELDS:
        values=[]
        for record in records:
            usage=(record.get('response') or {}).get('usage') or {}
            # A present-but-null top-level field must not hide valid raw usage.
            candidates=[source.get(name) for source in (record,usage) for name in names[field]]
            value=next((v for v in candidates if type(v) in (int,float) and math.isfinite(v)
                        and v>=0 and (field=='known_cost' or int(v)==v)),None)
            if value is not None:
                values.append(value if field=='known_cost' else int(value))
        result[field]=(math.fsum(values) if field=='known_cost' else sum(values)) if values else None
        result[unknown]=len(records)-len(values)
    return result


def cumulative_usage(entries):
    """Combine per-day usage without converting unknown usage into zero."""
    result={'attempts':sum(e['attempts'] for e in entries),
            'partial':any(e['partial'] for e in entries)}
    for field,unknown in USAGE_FIELDS:
        values=[e[field] for e in entries if e[field] is not None]
        result[field]=(math.fsum(values) if field=='known_cost' else sum(values)) if values else None
        result[unknown]=sum(e[unknown] for e in entries)
    return result


def load_history(root):
    """Discover saved dated runs -> filter study -> validate -> choose daily models.

    Explicitly filter persona/prompt/context settings. Duplicate runs on a date
    are resolved per model, choosing complete data first, then newest timestamp.
    Preserve source IDs/snapshots in provenance; never silently relabel a provider
    version. Missing or invalid models do not raise a global publication error.
    """
    config = yaml.safe_load((root / 'docs/site-config.yml').read_text(encoding='utf-8'))
    if config['expected_draws'] != 100:
        raise ValueError('The approved publication policy requires 100 sampled responses.')
    baseline = config['baseline']
    states, samples, features = validation_data(root, config['sample'])
    candidates, notices = {}, []
    for folder in sorted((root / 'data/llm_responses').iterdir()):
        if not folder.is_dir() or not re.match(r'^(\d{4}-\d{2}-\d{2}|[A-Za-z]{3}-\d{1,2})(?:-|_|$)',folder.name):
            continue
        paths = [folder/'results.parquet',folder/'summary.parquet']
        if not all(p.exists() for p in paths):
            notices.append({'run': folder.name,'reason': 'Saved results/summary not ready.'})
            continue
        try:
            rows, summary = (pl.read_parquet(p) for p in paths)
            for field, value in config['condition'].items():
                rows = rows.filter(pl.col(field)==value)
                summary = summary.filter(pl.col(field)==value)
            if rows.is_empty():
                notices.append({'run': folder.name,'reason': 'No rows match the website study condition.'})
                continue
            day = reporting_date(folder.name, rows['requested_at'].to_list(), config['timezone'])
            if day is None:
                continue
            attempts = []
            log = folder/'responses.jsonl'
            if log.exists():
                # Cost records stay local. The public export never contains prompts,
                # raw respondent IDs, API error bodies, or credentials.
                for line in log.read_text(encoding='utf-8').splitlines():
                    if line.strip():
                        try: attempts.append(json.loads(line))
                        except json.JSONDecodeError: pass  # incomplete append in an active run
            for key in config['models']:
                model_rows = rows.filter(pl.col('model_key')==key)
                if model_rows.is_empty():
                    continue
                model_ids = model_rows['model'].unique().to_list()
                if len(model_ids)!=1:
                    notices.append({'run':folder.name,'model':key,'reason':'Mixed provider model IDs in one condition.'})
                    continue
                model_summary = summary.filter(pl.col('model_key')==key)
                values = {}
                for state, ids in samples.items():
                    records = model_rows.filter(pl.col('state')==state).sort('persona_row').to_dicts()
                    saved = model_summary.filter(pl.col('state')==state).to_dicts()
                    values[slug(state)] = state_result(records, ids, saved)
                timestamps = [t for t in model_rows['requested_at'] if t]
                if not timestamps:
                    notices.append({'run':folder.name,'model':key,'reason':'No recorded collection timestamps.'})
                    continue
                start, end = min(timestamps), max(timestamps)
                relevant = [a for a in attempts if a.get('model_key')==key and
                            all(a.get(k)==v for k,v in config['condition'].items())]
                entry = {'run':folder.name,'date':day,'model_id':model_ids[0],
                         'model_snapshots':sorted(x for x in model_rows['model_snapshot'].unique().to_list() if x),
                         'started_at':start,'collected_at':end,'states':values,
                         'complete':all(v['eligible'] for v in values.values()),
                         'cost':request_usage(relevant,model_rows)}
                entry['senate'] = project_senate(dict(Counter(v['leader'] for v in values.values())),baseline) if entry['complete'] else None
                candidates.setdefault((day,key),[]).append(entry)
        except (ValueError, KeyError, pl.exceptions.PolarsError) as error:
            notices.append({'run':folder.name,'reason':f'Run could not be published: {error}'})
    snapshots = {}
    for (day,key), choices in candidates.items():
        selected = choose_candidate(choices)
        snapshots.setdefault(day,{'models':{}})['models'][key] = selected
        if len(choices)>1:
            notices.append({'date':day,'model':key,'reason':f'Selected {selected["run"]} from {len(choices)} candidates; no pooling.'})
    dates = sorted(snapshots)
    if not dates:
        raise ValueError('No dated runs match the configured study. See docs/README.md for folder naming.')
    latest = {key: next((d for d in reversed(dates) if snapshots[d]['models'].get(key,{}).get('complete')),None)
              for key in config['models']}
    sample_config = root/'data/personas'/config['sample']/'persona_config.yaml'
    sampling = yaml.safe_load(sample_config.read_text(encoding='utf-8')) if sample_config.exists() else {}
    return {'schema_version':2,'date':dates[-1],'dates':dates,'models':config['models'],
            'condition':config['condition'],'timezone':config['timezone'],'sample':config['sample'],
            'features':features,'states':states,'snapshots':snapshots,'latest':latest,
            'notices':notices,'baseline':baseline,'seed':sampling.get('seed'),
            'contacts':config.get('contacts',[])}


