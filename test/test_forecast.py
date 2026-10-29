"""Tests of the corrected forecast (src/forecast.py) and its saved outputs.

- With no error and identical personas, a draw equals the raw share, and the
  correction maps it exactly to intercept + slope * logit(share).
- Every draw allocates 100 seats: the fixed seats plus one winner per state.
- Summaries: win chances match the draws, intervals are ordered, the seat
  histogram counts every draw, and majority chances never exceed 1.
- Errors: no answers, mismatched arrays, or no state SD raise.
- add_corrected_forecasts skips benchmarks, incomplete days and models without
  a correction, and adding a new day leaves earlier forecasts unchanged.
- Saved outputs: 35 states per model/day, probabilities in [0, 1], ordered
  intervals and 100 seats in every saved draw.

Usage: uv run python -m unittest discover -s test -p 'test_forecast.py' -v
Generate the saved outputs with: uv run python src/forecast.py
"""

from pathlib import Path
import copy
import math
import sys
import tempfile
import unittest

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from forecast import (add_corrected_forecasts, logistic, seat_totals, simulate_states, summarise)

OUTPUT = ROOT / "data/forecast"
FIXED = {"democrat": 32, "republican": 31, "independent": 2}
CORRECTION = {"intercept": 0.2, "slope": 0.5, "state_sd": 0.0}


def identical(dem, rep, n=100):
    return (np.full(n, dem), np.full(n, rep))


class SimulationTests(unittest.TestCase):
    def test_no_error_returns_the_raw_share(self):
        personas = {"A": identical(0.3, 0.6), "B": identical(0.5, 0.2)}
        states, shares = simulate_states(np.random.default_rng(1), personas, draws=20,
                                         national_sd=0, state_sd=0)
        self.assertEqual(states, ["A", "B"])
        self.assertTrue(np.allclose(shares[:, 0], 1 / 3))
        self.assertTrue(np.allclose(shares[:, 1], 5 / 7))

    def test_correction_maps_the_logit_share(self):
        personas = {"A": identical(0.3, 0.6)}
        _, shares = simulate_states(np.random.default_rng(2), personas, draws=5,
                                    correction=CORRECTION, national_sd=0)
        expected = logistic(0.2 + 0.5 * math.log((1 / 3) / (2 / 3)))
        self.assertTrue(np.allclose(shares, expected))

    def test_nonvoting_acts_as_turnout_weight(self):
        # Likely Democratic voter and a probable non-voter who leans Republican.
        personas = {"A": (np.array([0.8, 0.05]), np.array([0.2, 0.15]))}
        _, shares = simulate_states(np.random.default_rng(3), personas, draws=4000,
                                    national_sd=0, state_sd=0)
        # Resampling two people averages back to sum(D) / sum(D + R) = 0.85 / 1.2.
        self.assertAlmostEqual(float(np.median(shares)), 0.85 / 1.2, places=6)

    def test_errors_raise(self):
        rng = np.random.default_rng(4)
        with self.assertRaises(ValueError):
            simulate_states(rng, {"A": (np.array([]), np.array([]))}, draws=5, state_sd=0.1)
        with self.assertRaises(ValueError):
            simulate_states(rng, {"A": (np.array([0.5]), np.array([0.2, 0.3]))}, draws=5, state_sd=0.1)
        with self.assertRaises(ValueError):
            simulate_states(rng, {"A": identical(0.5, 0.4)}, draws=5)

    def test_seats_add_to_one_hundred(self):
        shares = np.random.default_rng(5).uniform(0.3, 0.7, size=(200, 35))
        seats = seat_totals(shares, FIXED)
        total = seats["democratic_seats"] + seats["republican_seats"] + seats["independent_seats"]
        self.assertTrue((total == 100).all())
        self.assertTrue((seats["democratic_seats"] == 32 + (shares > 0.5).sum(axis=1)).all())


class SummaryTests(unittest.TestCase):
    def test_summary_matches_draws(self):
        rng = np.random.default_rng(6)
        personas = {f"S{i:02d}": identical(0.45 + i / 100, 0.5) for i in range(35)}
        states, shares = simulate_states(rng, personas, draws=2000, correction={**CORRECTION, "state_sd": 0.1})
        seats = seat_totals(shares, FIXED)
        state_rows, seat_summary = summarise(states, shares, seats, personas, {**CORRECTION, "state_sd": 0.1})
        first = state_rows["S00"]
        self.assertAlmostEqual(first["dem_win_chance"], float((shares[:, 0] > 0.5).mean()))
        self.assertAlmostEqual(first["raw_share"], 0.45 / 0.95)
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
            "nocorrection": copy.deepcopy(entry),
            "partial": {**copy.deepcopy(entry), "complete": False},
            "polls": {"kind": "external_forecast", "complete": True, "states": {}},
        }}
    return {"baseline": {"fixed_seats": FIXED}, "states": states, "snapshots": snapshots}


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "data/model_validation").mkdir(parents=True)
        pl.DataFrame({"model_key": ["jev", "partial"], "calibration_intercept": [0.0, 0.0],
                      "calibration_slope": [0.5, 0.5], "calibration_residual_sd": [0.1, 0.1]}
                     ).write_parquet(root / "data/model_validation/backcast_summary.parquet")
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_only_corrected_complete_models_get_forecasts(self):
        history = add_corrected_forecasts(toy_history(["2026-10-30"]), self.root, draws=200)
        models = history["snapshots"]["2026-10-30"]["models"]
        self.assertIsNotNone(models["jev"]["forecast"])
        for key in ("nocorrection", "partial", "polls"):
            self.assertIsNone(models[key]["forecast"], key)
        self.assertEqual(len(models["jev"]["forecast"]["states"]), 35)

    def test_new_day_leaves_earlier_forecast_unchanged(self):
        one = add_corrected_forecasts(toy_history(["2026-10-30"]), self.root, draws=200)
        two = add_corrected_forecasts(toy_history(["2026-10-30", "2026-10-31"]), self.root, draws=200)
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
        for column in ("raw_share", "corrected_share", "median", "low", "high", "dem_win_chance"):
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
