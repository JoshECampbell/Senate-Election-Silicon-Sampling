"""Tests of the bootstrap forecast (src/forecast.py) and its saved outputs.

- With identical personas every resample equals the state's share, and shares
  use sum P(D) / sum(P(D) + P(R)), so P(Would not vote) acts as a turnout weight.
- Resampling varies a mixed state's share and stays between its personas.
- Every draw allocates 100 seats: the fixed seats plus one winner per state.
- Summaries: win chances match the draws, intervals are ordered, the seat
  histogram counts every draw, and majority chances never exceed 1.
- Errors: no answers or mismatched arrays raise.
- add_bootstrap_forecasts skips benchmarks and incomplete days, and adding a
  new day leaves earlier forecasts unchanged.
- Saved outputs: 35 states per model/day, probabilities in [0, 1], ordered
  intervals and 100 seats in every saved draw.

Usage: uv run python -m unittest discover -s test -p 'test_forecast.py' -v
Generate the saved outputs with: uv run python src/forecast.py
"""

from pathlib import Path
import copy
import sys
import unittest

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from forecast import add_bootstrap_forecasts, bootstrap_states, seat_totals, summarise

OUTPUT = ROOT / "data/forecast"
FIXED = {"democrat": 32, "republican": 31, "independent": 2}


def identical(dem, rep, n=100):
    return (np.full(n, dem), np.full(n, rep))


class BootstrapTests(unittest.TestCase):
    def test_identical_personas_return_the_share(self):
        personas = {"A": identical(0.3, 0.6), "B": identical(0.5, 0.2)}
        states, shares = bootstrap_states(np.random.default_rng(1), personas, draws=20)
        self.assertEqual(states, ["A", "B"])
        self.assertTrue(np.allclose(shares[:, 0], 1 / 3))
        self.assertTrue(np.allclose(shares[:, 1], 5 / 7))

    def test_nonvoting_acts_as_turnout_weight(self):
        # Likely Democratic voter and a probable non-voter who leans Republican.
        personas = {"A": (np.array([0.8, 0.05]), np.array([0.2, 0.15]))}
        _, shares = bootstrap_states(np.random.default_rng(3), personas, draws=4000)
        # Resampling two people averages back to sum(D) / sum(D + R) = 0.85 / 1.2.
        self.assertAlmostEqual(float(np.median(shares)), 0.85 / 1.2, places=6)

    def test_resampling_varies_and_stays_between_personas(self):
        personas = {"A": (np.array([0.9, 0.1] * 50), np.array([0.1, 0.9] * 50))}
        _, shares = bootstrap_states(np.random.default_rng(4), personas, draws=500)
        self.assertGreater(shares.std(), 0)
        self.assertTrue(((shares >= 0.1) & (shares <= 0.9)).all())

    def test_errors_raise(self):
        rng = np.random.default_rng(5)
        with self.assertRaises(ValueError):
            bootstrap_states(rng, {"A": (np.array([]), np.array([]))}, draws=5)
        with self.assertRaises(ValueError):
            bootstrap_states(rng, {"A": (np.array([0.5]), np.array([0.2, 0.3]))}, draws=5)

    def test_seats_add_to_one_hundred(self):
        shares = np.random.default_rng(6).uniform(0.3, 0.7, size=(200, 35))
        seats = seat_totals(shares, FIXED)
        total = seats["democratic_seats"] + seats["republican_seats"] + seats["independent_seats"]
        self.assertTrue((total == 100).all())
        self.assertTrue((seats["democratic_seats"] == 32 + (shares > 0.5).sum(axis=1)).all())


class SummaryTests(unittest.TestCase):
    def test_summary_matches_draws(self):
        rng = np.random.default_rng(7)
        personas = {f"S{i:02d}": (np.array([0.2 + i / 50, 0.8] * 50), np.array([0.7, 0.3] * 50))
                    for i in range(35)}
        states, shares = bootstrap_states(rng, personas, draws=2000)
        seats = seat_totals(shares, FIXED)
        state_rows, seat_summary = summarise(states, shares, seats, personas)
        first = state_rows["S00"]
        self.assertAlmostEqual(first["dem_win_chance"], float((shares[:, 0] > 0.5).mean()))
        self.assertAlmostEqual(first["share"], 1.0 / 2.0)
        for row in state_rows.values():
            self.assertLessEqual(row["low"], row["median"])
            self.assertLessEqual(row["median"], row["high"])
        self.assertEqual(sum(seat_summary["histogram"].values()), 2000)
        self.assertLessEqual(seat_summary["low"], seat_summary["median"])
        self.assertLessEqual(seat_summary["median"], seat_summary["high"])
        chances = (seat_summary["democratic_majority"], seat_summary["republican_majority"],
                   seat_summary["no_majority"])
        self.assertAlmostEqual(sum(chances), 1.0)
        self.assertTrue(all(0 <= c <= 1 for c in chances))


def toy_history(days):
    points = [{"draw": i + 1, "p_democrat": 0.4, "p_republican": 0.5, "p_third_party": 0.0,
               "p_would_not_vote": 0.1} for i in range(100)]
    states = {f"s{i:02d}": {"name": f"State {i}"} for i in range(35)}
    entry = {"run": "run", "complete": True, "states": {s: {"points": points} for s in states}}
    snapshots = {}
    for day in days:
        snapshots[day] = {"models": {
            "jev": copy.deepcopy(entry),
            "partial": {**copy.deepcopy(entry), "complete": False},
            "polls": {"kind": "external_forecast", "complete": True, "states": {}},
        }}
    return {"baseline": {"fixed_seats": FIXED}, "states": states, "snapshots": snapshots}


class HistoryTests(unittest.TestCase):
    def test_only_complete_synthetic_models_get_forecasts(self):
        history = add_bootstrap_forecasts(toy_history(["2026-10-30"]), draws=200)
        models = history["snapshots"]["2026-10-30"]["models"]
        self.assertIsNotNone(models["jev"]["forecast"])
        for key in ("partial", "polls"):
            self.assertIsNone(models[key]["forecast"], key)
        self.assertEqual(len(models["jev"]["forecast"]["states"]), 35)

    def test_new_day_leaves_earlier_forecast_unchanged(self):
        one = add_bootstrap_forecasts(toy_history(["2026-10-30"]), draws=200)
        two = add_bootstrap_forecasts(toy_history(["2026-10-30", "2026-10-31"]), draws=200)
        self.assertEqual(one["snapshots"]["2026-10-30"]["models"]["jev"]["forecast"],
                         two["snapshots"]["2026-10-30"]["models"]["jev"]["forecast"])


@unittest.skipUnless((OUTPUT / "seat_summary.parquet").exists(), "Run src/forecast.py first.")
class SavedOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.states = pl.read_parquet(OUTPUT / "state_forecasts.parquet")
        cls.seats = pl.read_parquet(OUTPUT / "seat_summary.parquet")
        cls.draws = pl.read_parquet(OUTPUT / "seat_draws.parquet")

    def test_every_state_for_every_model_and_day(self):
        counts = self.states.group_by("date", "model_key").agg(pl.col("state").n_unique())
        self.assertTrue((counts["state"] == 35).all())
        self.assertEqual(counts.height, self.seats.height)

    def test_values_are_bounded_and_ordered(self):
        for column in ("share", "median", "low", "high", "dem_win_chance"):
            self.assertTrue(self.states[column].is_between(0, 1).all(), column)
        self.assertTrue((self.states["low"] <= self.states["high"]).all())
        self.assertTrue(((self.seats["low"] <= self.seats["median"])
                         & (self.seats["median"] <= self.seats["high"])).all())

    def test_saved_draws_total_one_hundred(self):
        total = self.draws.select(pl.sum_horizontal("democratic_seats", "republican_seats",
                                                    "independent_seats")).to_series()
        self.assertTrue((total == 100).all())


if __name__ == "__main__":
    unittest.main()
