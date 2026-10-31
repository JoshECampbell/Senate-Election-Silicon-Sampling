"""Tests run:
- Convert forecast margins to implied two-candidate shares, including ties and invalid bounds.
- Preserve independent candidates, 100-seat totals and unavailable historical dates.
- Keep saved forecasts after a failed fetch and draw forecast markers without fabricated personas.
- Reject wrong-date or duplicate-state API responses without overwriting saved history.

Usage: uv run python -m unittest discover -s test -p 'test_polling_forecast.py' -v
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import json
import io
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from polling_forecast import KEY, add_forecasts, fetch_forecast, implied_shares, carry_forward_forecasts
from site_figures import response_figure
from src.create_personas import SENATE_STATES_2026


class PollingForecastTests(unittest.TestCase):
    def test_carry_forward_only_uses_earlier_actual_snapshots(self):
        def entry(day, share):
            return {'date': day, 'kind': 'external_forecast', 'states': {'a': {'means': {'p_democrat': share}}}}
        history = {'dates': ['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30'],
                   'latest': {KEY: '2026-10-29'}, 'snapshots': {
                       '2026-10-26': {'models': {}},
                       '2026-10-27': {'models': {KEY: entry('2026-10-27', .4)}},
                       '2026-10-28': {'models': {}},
                       '2026-10-29': {'models': {KEY: entry('2026-10-29', .45)}},
                       '2026-10-30': {'models': {}}}}
        carry_forward_forecasts(history)
        self.assertNotIn(KEY, history['snapshots']['2026-10-26']['models'])
        reused = history['snapshots']['2026-10-28']['models'][KEY]
        self.assertTrue(reused['carried_forward'])
        self.assertEqual(reused['source_date'], '2026-10-27')
        self.assertEqual(reused['states']['a']['means']['p_democrat'], .4)
        latest = history['snapshots']['2026-10-30']['models'][KEY]
        self.assertEqual(latest['source_date'], '2026-10-29')
        self.assertEqual(latest['states']['a']['means']['p_democrat'], .45)
        self.assertEqual(history['latest'][KEY], '2026-10-29')
        reused['states']['a']['means']['p_democrat'] = .1
        self.assertEqual(history['snapshots']['2026-10-27']['models'][KEY]['states']['a']['means']['p_democrat'], .4)

    def test_no_benchmark_is_a_safe_noop(self):
        history = {'dates': ['2026-10-30'], 'snapshots': {'2026-10-30': {'models': {}}}}
        carry_forward_forecasts(history)
        self.assertEqual(history['snapshots']['2026-10-30']['models'], {})

    def test_fetch_accepts_matching_date_and_rejects_bad_date_or_coverage(self):
        data = {'dataset': 'senate', 'asOf': '2026-10-28', 'rows': [
            {'name': name + ' Senate', 'left_party': 'D', 'best_bet_margin': 6}
            for name in SENATE_STATES_2026.values()]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch('polling_forecast.urlopen', return_value=io.StringIO(json.dumps(data))):
                self.assertTrue(fetch_forecast(root, expected_date='2026-10-28'))
            saved = root / 'data/polling_forecast/2026-10-28.json'
            original = saved.read_bytes()
            with patch('polling_forecast.urlopen', return_value=io.StringIO(json.dumps(data))):
                self.assertFalse(fetch_forecast(root, expected_date='2026-10-29'))
            data['rows'][0] = data['rows'][1]
            with patch('polling_forecast.urlopen', return_value=io.StringIO(json.dumps(data))):
                self.assertFalse(fetch_forecast(root, expected_date='2026-10-28'))
            self.assertEqual(saved.read_bytes(), original)

    def test_margin_is_vote_share_not_win_probability(self):
        self.assertEqual(implied_shares(6), (.53, .47))
        self.assertEqual(implied_shares(-100), (0, 1))
        self.assertEqual(implied_shares(0), (.5, .5))
        with self.assertRaises(ValueError):
            implied_shares(float('nan'))

    def test_archive_maps_independents_and_preserves_missing_days(self):
        # 35 fictitious study races, with one independent win and one exact tie.
        names = [f'State {i}' for i in range(35)]
        history = {'models': {}, 'latest': {}, 'dates': ['2026-10-26'],
                   'date': '2026-10-26', 'snapshots': {'2026-10-26': {'models': {}}},
                   'states': {n.lower().replace(' ', '-'): {'name': n} for n in names},
                   'baseline': {'chamber_seats': 100, 'contested_seats': 35,
                                'fixed_seats': {'democrat': 32, 'republican': 31, 'independent': 2}}}
        data = {'asOf': '2026-10-27', 'licence': 'CC BY 4.0', 'attribution': 'Polling Forecast',
                'rows': [{'name': n + ' Senate', 'key': str(i), 'left_party': 'I' if i == 0 else 'D',
                          'best_bet_margin': 0 if i == 1 else 6, 'chance_left': .99}
                         for i, n in enumerate(names)]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'data/polling_forecast'
            archive.mkdir(parents=True)
            path = archive / '2026-10-27.json'
            path.write_text(json.dumps({'forecast': data, 'retrieved_at': '2026-10-27T15:00:00+00:00'}))
            add_forecasts(history, root)
            before = path.read_bytes()
            with patch('polling_forecast.urlopen', side_effect=URLError('offline')):
                fetch_forecast(root)
            self.assertEqual(path.read_bytes(), before)
        self.assertNotIn(KEY, history['snapshots']['2026-10-26']['models'])
        entry = history['snapshots']['2026-10-27']['models'][KEY]
        self.assertEqual(entry['senate']['totals'],
                         {'democrat': 65, 'republican': 31, 'independent': 3, 'unallocated': 1})
        independent = entry['states']['state-0']
        self.assertEqual(independent['means']['p_third_party'], .53)
        self.assertIsNone(independent['means']['p_democrat'])
        self.assertIsNone(independent['means']['p_would_not_vote'])
        self.assertEqual(independent['points'], [])
        # The forecast contributes a mean marker, never 100 fabricated personas.
        content = response_figure('state-0', history, 'p_third_party', history['date'])
        self.assertIn('mean-dot', content)
        self.assertNotIn('persona-dot', content)
        content = response_figure('state-0', history, 'p_would_not_vote', history['date'])
        self.assertNotIn('mean-dot', content)


if __name__ == '__main__':
    unittest.main()
