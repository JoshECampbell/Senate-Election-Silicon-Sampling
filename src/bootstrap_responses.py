"""Bootstrap the four original response means, preserving complete draw vectors.

Each replicate samples 100 existing draw positions equally with replacement.
The bootstrap SE is the sample SD of the replicate means, not SD/sqrt(10000).
This describes cohort-resampling variation, not model or election uncertainty.
"""
from pathlib import Path
import zlib

import numpy as np
import polars as pl

from site_data import CATEGORIES

RESAMPLES = 10_000
SAMPLE_SIZE = 100
BASE_SEED = 2026
COLUMNS = [c[0] for c in CATEGORIES]


def bootstrap_means(probabilities, rng, resamples=RESAMPLES):
    values = np.asarray(probabilities, dtype=float)
    if values.shape != (SAMPLE_SIZE, 4):
        raise ValueError('Expected exactly 100 complete four-option persona draws.')
    if (not np.isfinite(values).all() or (values < 0).any() or (values > 1).any()
            or (np.abs(values.sum(axis=1) - 1) > 1e-6).any()):
        raise ValueError('Persona probabilities must be finite, bounded and sum to one.')
    if resamples < 2:
        raise ValueError('At least two bootstrap replicates are required for a standard error.')
    means = np.empty((resamples, 4))
    for start in range(0, resamples, 500):
        stop = min(start + 500, resamples)
        indices = rng.integers(0, SAMPLE_SIZE, size=(stop - start, SAMPLE_SIZE))
        # Select the entire vector: all categories use the same sampled people.
        means[start:stop] = values[indices].mean(axis=1)
    return means


def summarise_means(probabilities, means):
    values = np.asarray(probabilities, dtype=float)
    return {column: {'mean': float(values[:, i].mean()),
                     'sem': float(means[:, i].std(ddof=1)),
                     'low': float(np.quantile(means[:, i], .05)),
                     'high': float(np.quantile(means[:, i], .95)),
                     'median': float(np.median(means[:, i]))}
            for i, column in enumerate(COLUMNS)}


def seat_draws_from_means(state_means, fixed):
    """Use the classic three-voting-category winner rule; preserve exact ties."""
    resamples = len(next(iter(state_means.values())))
    totals = {key: np.full(resamples, fixed.get(key, 0), dtype=int)
              for key in ('democrat', 'republican', 'independent', 'unallocated')}
    for means in state_means.values():
        voting = means[:, :3]
        largest = voting.max(axis=1)
        unique = (voting == largest[:, None]).sum(axis=1) == 1
        for i, key in enumerate(('democrat', 'republican', 'independent')):
            totals[key] += unique & (voting[:, i] == largest)
        totals['unallocated'] += ~unique
    return totals


def add_response_bootstraps(history, site, cache, renderer, resamples=RESAMPLES):
    """Save four-category SEs and plot every model/day's full-Senate replicates."""
    history['response_bootstrap_settings'] = {
        'draws_per_resample': SAMPLE_SIZE, 'resamples': resamples,
        'seed': BASE_SEED, 'interval': [.05, .95],
        'sem_definition': 'sample standard deviation of bootstrap mean estimates'}
    rows, seat_rows, seat_draw_frames = [], [], []
    for day, snapshot in history['snapshots'].items():
        for key, entry in snapshot['models'].items():
            if entry.get('kind') == 'external_forecast':
                continue
            state_means = {}
            for state, values in entry['states'].items():
                if not values['eligible']:
                    continue
                points = sorted(values['points'], key=lambda p: p['draw'])
                probabilities = [[p[c] for c in COLUMNS] for p in points]
                rng = np.random.default_rng([BASE_SEED, zlib.crc32(day.encode()),
                                             zlib.crc32(key.encode()), zlib.crc32(state.encode())])
                means = bootstrap_means(probabilities, rng, resamples)
                state_means[state] = means
                summary = summarise_means(probabilities, means)
                values['bootstrap'] = summary
                for column, result in summary.items():
                    rows.append({'date': day, 'model_key': key,
                                 'state': history['states'][state]['name'], 'option': column,
                                 'persona_draws': SAMPLE_SIZE, 'resamples': resamples, **result})
            if entry.get('complete') and len(state_means) == 35:
                totals = seat_draws_from_means(state_means, history['baseline']['fixed_seats'])
                summary = {party: {'mean': float(draws.mean()), 'sem': float(draws.std(ddof=1)),
                                   'median': float(np.median(draws)),
                                   'low': float(np.quantile(draws, .05)),
                                   'high': float(np.quantile(draws, .95))}
                           for party, draws in totals.items()}
                entry['bootstrap_senate'] = {'resamples': resamples, 'parties': summary}
                cache.render(Path(site)/f'figures/{day}/bootstrap/{key}.svg', renderer,
                             history['models'][key]['label'],
                             {p: totals[p].tolist() for p in ('democrat', 'republican')},
                             entry['senate']['totals'], summary)
                for party, result in summary.items():
                    seat_rows.append({'date': day, 'model_key': key, 'party': party,
                                      'resamples': resamples, **result})
                seat_draw_frames.append(pl.DataFrame({'date': day, 'model_key': key,
                                                      'replicate': np.arange(resamples), **totals}))
    folder = Path(site)/'data'
    folder.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(folder/'response_bootstrap_summary.parquet')
    pl.DataFrame(seat_rows).write_parquet(folder/'senate_bootstrap_summary.parquet')
    if seat_draw_frames:
        pl.concat(seat_draw_frames).write_parquet(folder/'senate_bootstrap_draws.parquet')
    return history
