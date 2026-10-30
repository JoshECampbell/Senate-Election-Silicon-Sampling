"""Collect and prepare the Polling Forecast Senate benchmark.

Workflow
--------
1. Local Quarto renders call --fetch; Actions collects once in its polling job
   and sets SKIP_FORECAST_FETCH=1 while rendering saved inputs.
2. Download all 35 races in one request and save the original JSON under
   data/polling_forecast/YYYY-MM-DD.json, using the API's asOf date.
3. Website preparation reads those saved days for the headline, time series,
   and state overview. Older dates are never invented or backfilled.

Calculation (an explicit TWO-CANDIDATE assumption)
------------------------------------------------
best_bet_margin is left minus Republican, in percentage points. Assuming their
shares sum to 1: share_left = (100 + best_bet_margin) / 200;
share_right = 1 - share_left. For example, +6 points means 53% left, 47% right.
These are IMPLIED shares, not published vote shares or raw polling averages.
chance_left is a probability of WINNING and is NOT used in this calculation.
The left candidate may be independent: preserve left_party rather than calling
every left candidate Democratic. Other parties and non-voting are unmeasured.
The larger implied share wins one seat; exact ties remain unallocated. Add the
65 fixed seats from docs/site-config.yml to obtain a 100-seat projection.

The latest successful response for an asOf day replaces that day's saved copy.
If a fetch fails, rendering uses saved days and prints a notice. Rendering only
collects when it runs: run daily to accumulate daily history. No API key needed.
Source: https://www.pollingforecast.com/us/data (CC BY 4.0; credit required).
Usage (repository root): uv run python src/polling_forecast.py --fetch
"""

from argparse import ArgumentParser
from collections import Counter
import copy
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from site_data import CATEGORIES, project_senate, slug

URL = 'https://www.pollingforecast.com/api/us/senate'
KEY = 'polling_forecast'
MODEL = {'label': 'Polling Forecast', 'full_name': 'Polling Forecast',
         'shape': 'diamond', 'dash': '9 3 2 3', 'kind': 'external_forecast'}
PARTIES = {'D': 'p_democrat', 'R': 'p_republican', 'I': 'p_third_party'}


def implied_shares(margin):
    """Convert a percentage-point margin to two shares, without using win odds."""
    if not isinstance(margin, (int, float)) or not -100 <= margin <= 100:
        raise ValueError('Forecast margin must be between -100 and 100 points.')
    left = (100 + margin) / 200
    return left, 1 - left


def fetch_forecast(root=ROOT, expected_date=None):
    """Save one dated API response; keep existing files if the request fails."""
    try:
        request = Request(URL, headers={'User-Agent': 'Senate-Election-Silicon-Sampling/1.0'})
        with urlopen(request, timeout=20) as response:
            data = json.load(response)
        day = date.fromisoformat(data['asOf']).isoformat()
        if expected_date is not None and day != expected_date:
            raise ValueError(f'Forecast asOf {day} does not match collection day {expected_date}.')
        if data['dataset'] != 'senate' or len(data['rows']) != 35:
            raise ValueError('Expected the 35 Senate races.')
        for row in data['rows']:
            implied_shares(row['best_bet_margin'])
            PARTIES[row['left_party']]
        from src.create_personas import SENATE_STATES_2026
        expected_states = {slug(name) for name in SENATE_STATES_2026.values()}
        actual_states = [slug(row['name'].split(' Senate')[0]) for row in data['rows']]
        if len(set(actual_states)) != 35 or set(actual_states) != expected_states:
            raise ValueError('Expected one forecast for each of the 35 study states.')
        folder = root / 'data/polling_forecast'
        folder.mkdir(parents=True, exist_ok=True)
        # Retain original source fields and a separate retrieval timestamp.
        saved = {'source_url': URL, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                 'forecast': data}
        (folder / f'{day}.json').write_text(json.dumps(saved, indent=2), encoding='utf-8')
        print(f'Saved Polling Forecast: {day}, 35 races.')
        return True
    except (URLError, OSError, ValueError, KeyError) as error:
        print(f'Polling Forecast fetch unavailable; using saved history if present: {error}')
        return False


def add_forecasts(history, root=ROOT):
    """Adapt archived forecasts to the site's chart records, without persona draws."""
    history['models'][KEY] = dict(MODEL)
    history['latest'][KEY] = None
    for path in sorted((root / 'data/polling_forecast').glob('????-??-??.json')):
        saved = json.loads(path.read_text(encoding='utf-8'))
        data = saved['forecast']
        day = date.fromisoformat(data['asOf']).isoformat()
        states = {}
        for row in data['rows']:
            # Source names identify the state, including Florida/Ohio specials.
            state = slug(row['name'].split(' Senate')[0])
            left, right = implied_shares(row['best_bet_margin'])
            left_column = PARTIES[row['left_party']]
            means = {column: None for column, _, _ in CATEGORIES}
            means.update({left_column: left, 'p_republican': right})
            states[state] = {'eligible': True, 'means': means, 'points': [],
                             'leader': left_column if left > right else
                                       'p_republican' if right > left else 'unallocated',
                             'margin_pp': row['best_bet_margin'], 'race_key': row['key'],
                             'left_party': row['left_party']}
        if set(states) != set(history['states']):
            raise ValueError(f'{path}: forecast races do not match the 35 study states.')
        entry = {'run': 'Polling Forecast API', 'date': day, 'kind': 'external_forecast',
                 'model_id': URL, 'model_snapshots': [], 'collected_at': saved['retrieved_at'],
                 'complete': True, 'states': states, 'attribution': data['attribution'],
                 'licence': data['licence'], 'source_url': URL,
                 'senate': project_senate(dict(Counter(s['leader'] for s in states.values())),
                                          history['baseline'])}
        history['snapshots'].setdefault(day, {'models': {}})['models'][KEY] = entry
        history['latest'][KEY] = day
    history['dates'] = sorted(history['snapshots'])
    history['date'] = history['dates'][-1]


def carry_forward_forecasts(history):
    """Fill later reporting-day displays, marking every reused benchmark value.

    Actual archived forecasts and their source dates remain unchanged. Nothing
    is filled before the first available forecast, and no network call is made.
    history['latest'] continues to identify the latest actual API snapshot.
    """
    latest = None
    source_day = None
    for day in sorted(history['dates']):
        models = history['snapshots'][day]['models']
        entry = models.get(KEY)
        if entry is not None and not entry.get('carried_forward'):
            entry['source_date'] = day
            entry['carried_forward'] = False
            latest, source_day = entry, day
        elif entry is None and latest is not None:
            entry = copy.deepcopy(latest)
            entry.update(date=day, source_date=source_day, carried_forward=True,
                         run='Polling Forecast API (last available)')
            models[KEY] = entry
    return history


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='Download and save the current forecast.')
    # CI has a separate collection job: rendering must use its saved snapshot.
    if parser.parse_args().fetch and os.environ.get('SKIP_FORECAST_FETCH') != '1':
        fetch_forecast()
