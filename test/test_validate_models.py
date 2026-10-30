"""Tests of the model-validation metrics on hand-made answers with known scores,
plus checks on the saved validation outputs when they exist.

- Benchmarks map CES codes to the four options; "Not sure" and missing answers
  are not scored, and invalid model answers are never scored.
- Accuracy, the most-common-answer baseline, log loss, Brier score and
  two-party accuracy match values worked out by hand.
- A model with no valid answers still appears, with zero scored rows.
- Option shares compare mean probabilities with answer shares.
- Calibration bins hold every two-party row once.
- State shares use sum P(D) / sum(P(D) + P(R)), and run stability reports the
  spread across runs.
- Back-cast: state errors against official results, the per-model summary, and
  an error for unmatched states.
- Saved outputs: one row per run x model x benchmark, scores in range, and
  states covering all 35 Senate races.

Usage: uv run python -m unittest discover -s test -p 'test_validate_models.py' -v
"""

from pathlib import Path
import math
import sys
import unittest

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from validate_models import (BENCHMARKS, backcast_states, backcast_summary, calibration, option_shares,
                             run_stability, score_individuals, scored_rows, state_comparison)

OUTPUT = ROOT / "data/model_validation"
SCHEMA = {"run": pl.String, "model_key": pl.String, "state": pl.String, "caseid": pl.Float64,
          "CC25_363": pl.Int64, "presvote24post": pl.Int64, "probability_valid": pl.Boolean,
          "p_democrat": pl.Float64, "p_republican": pl.Float64, "p_third_party": pl.Float64,
          "p_would_not_vote": pl.Float64}


def row(house, vote, probs, model="m", run="r1", state="A", valid=True):
    dem, rep, third, nonvote = probs if probs else (None,) * 4
    return {"run": run, "model_key": model, "state": state, "caseid": 1.0, "CC25_363": house,
            "presvote24post": vote, "probability_valid": valid, "p_democrat": dem,
            "p_republican": rep, "p_third_party": third, "p_would_not_vote": nonvote}


def frame(rows):
    return pl.DataFrame(rows, schema=SCHEMA)


# Three scorable personas: a Democrat, a Republican and a non-voter, plus one
# "Not sure" and one invalid answer that must not be scored.
EXAMPLE = frame([
    row(2, 1, (0.7, 0.2, 0.0, 0.1)),
    row(3, 2, (0.6, 0.3, 0.0, 0.1)),
    row(1, 9, (0.1, 0.1, 0.0, 0.8)),
    row(4, 1, (0.5, 0.5, 0.0, 0.0)),
    row(2, 1, None, valid=False),
])


class ScoringTests(unittest.TestCase):
    def house(self, table):
        return table.filter(pl.col("benchmark") == "2026 House intention").row(0, named=True)

    def test_unscorable_rows_are_dropped(self):
        rows = scored_rows(EXAMPLE, "2026 House intention")
        self.assertEqual(rows["target"].to_list(), ["Democrat", "Republican", "Would not vote"])

    def test_scores_match_hand_calculation(self):
        scores = self.house(score_individuals(EXAMPLE))
        self.assertEqual(scores["rows"], 5)
        self.assertAlmostEqual(scores["coverage"], 0.8)
        self.assertEqual(scores["scored"], 3)
        self.assertAlmostEqual(scores["accuracy"], 2 / 3)           # Republican row picks Democrat
        self.assertAlmostEqual(scores["baseline_accuracy"], 1 / 3)  # three different answers
        self.assertAlmostEqual(scores["two_party_accuracy"], 1 / 2)
        expected_log_loss = -(math.log(0.7) + math.log(0.3) + math.log(0.8)) / 3
        self.assertAlmostEqual(scores["log_loss"], expected_log_loss)
        brier = ((0.3 ** 2 + 0.2 ** 2 + 0.1 ** 2) + (0.6 ** 2 + 0.7 ** 2 + 0.1 ** 2)
                 + (0.1 ** 2 + 0.1 ** 2 + 0.2 ** 2)) / 3
        self.assertAlmostEqual(scores["brier"], brier)

    def test_2024_vote_maps_other_candidates_to_third_party(self):
        mapping = BENCHMARKS["2024 presidential vote"][1]
        self.assertEqual({mapping[code] for code in (3, 4, 5, 6, 8)}, {"Third party"})
        self.assertEqual(mapping[9], "Would not vote")

    def test_model_with_no_valid_answers_still_appears(self):
        silent = frame([row(2, 1, None, model="silent", valid=False)] * 3)
        scores = score_individuals(pl.concat([EXAMPLE, silent]))
        silent_row = scores.filter(model_key="silent", benchmark="2026 House intention")
        self.assertEqual(silent_row.height, 1)
        self.assertEqual(silent_row["scored"].item(), 0)
        self.assertEqual(silent_row["coverage"].item(), 0)
        self.assertIsNone(silent_row["accuracy"].item())

    def test_option_shares(self):
        shares = option_shares(EXAMPLE).filter(pl.col("benchmark") == "2026 House intention")
        democrat = shares.filter(option="Democrat").row(0, named=True)
        self.assertAlmostEqual(democrat["predicted"], (0.7 + 0.6 + 0.1) / 3)
        self.assertAlmostEqual(democrat["actual"], 1 / 3)
        self.assertAlmostEqual(democrat["error"], democrat["predicted"] - democrat["actual"])

    def test_calibration_bins_hold_each_row_once(self):
        rows = frame([row(2, 1, (d, 1 - d, 0.0, 0.0)) for d in (0.05, 0.15, 0.55, 0.95, 0.95)])
        table = calibration(rows)
        self.assertEqual(table["n"].sum(), 5)
        top = table.filter(bin="0.9-1.0").row(0, named=True)
        self.assertEqual(top["n"], 2)
        self.assertAlmostEqual(top["actual"], 1.0)


class StateTests(unittest.TestCase):
    def test_two_party_share_weights_by_turnout(self):
        rows = frame([row(2, 1, (0.8, 0.2, 0.0, 0.0)), row(3, 2, (0.05, 0.15, 0.0, 0.8))])
        table = state_comparison(rows).row(0, named=True)
        self.assertAlmostEqual(table["predicted_two_party"], 0.85 / 1.2)
        self.assertAlmostEqual(table["persona_two_party"], 0.5)
        self.assertAlmostEqual(table["error_vs_personas"], 0.85 / 1.2 - 0.5)

    def test_ces_benchmark_is_weighted(self):
        ces = pl.DataFrame({"inputstate": [1, 1, 1], "CC25_363": [2, 3, 3],
                            "commonweight": [2.0, 1.0, 1.0]})
        rows = frame([row(2, 1, (0.6, 0.4, 0.0, 0.0), state="Alabama")])
        table = state_comparison(rows, ces).row(0, named=True)
        self.assertAlmostEqual(table["ces_two_party"], 0.5)
        self.assertAlmostEqual(table["error_vs_ces"], 0.1)

    def test_run_stability(self):
        rows = frame([row(2, 1, (0.6, 0.4, 0.0, 0.0), run="r1"),
                      row(2, 1, (0.4, 0.6, 0.0, 0.0), run="r2")])
        stability = run_stability(state_comparison(rows)).row(0, named=True)
        self.assertEqual(stability["runs"], 2)
        self.assertAlmostEqual(stability["mean"], 0.5)
        self.assertAlmostEqual(stability["min"], 0.4)
        self.assertAlmostEqual(stability["max"], 0.6)


class BackcastTests(unittest.TestCase):
    ACTUAL = pl.DataFrame({"state": ["A", "B"], "harris_two_party": [0.5, 0.4]})

    def test_state_error_against_official_result(self):
        rows = frame([row(1, 1, (0.6, 0.4, 0.0, 0.0), state="A"),
                      row(2, 2, (0.3, 0.7, 0.0, 0.0), state="B"),
                      row(2, 2, None, state="B", valid=False)])
        states = backcast_states(rows, self.ACTUAL)
        self.assertAlmostEqual(states.filter(state="A")["error"].item(), 0.1)
        self.assertAlmostEqual(states.filter(state="B")["error"].item(), -0.1)

    def test_summary(self):
        rows = frame([row(1, 1, (0.6, 0.4, 0.0, 0.0), state="A"),
                      row(2, 2, (0.5, 0.5, 0.0, 0.0), state="B")])
        summary = backcast_summary(backcast_states(rows, self.ACTUAL)).row(0, named=True)
        self.assertEqual(summary["states"], 2)
        self.assertAlmostEqual(summary["mean_error"], 0.1)
        self.assertAlmostEqual(summary["mean_abs_error"], 0.1)
        self.assertAlmostEqual(summary["max_abs_error"], 0.1)
        self.assertAlmostEqual(summary["winner_agreement"], 0.5)  # A's official 0.5 is not a Democratic win

    def test_state_without_result_raises(self):
        rows = frame([row(1, 1, (0.6, 0.4, 0.0, 0.0), state="C")])
        with self.assertRaises(ValueError):
            backcast_states(rows, self.ACTUAL)


@unittest.skipUnless((OUTPUT / "individual.parquet").exists(),
                     "Run src/validate_models.py to create the saved outputs.")
class SavedOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.individual = pl.read_parquet(OUTPUT / "individual.parquet")
        cls.states = pl.read_parquet(OUTPUT / "states.parquet")

    def test_one_row_per_run_model_and_benchmark(self):
        keys = self.individual.select("run", "model_key", "benchmark")
        self.assertEqual(keys.unique().height, self.individual.height)
        self.assertEqual(set(self.individual["benchmark"]), set(BENCHMARKS))

    def test_scores_are_in_range(self):
        scored = self.individual.filter(pl.col("scored") > 0)
        for column in ("coverage", "accuracy", "baseline_accuracy", "two_party_accuracy"):
            self.assertTrue(scored[column].is_between(0, 1).all(), column)
        self.assertTrue((scored["log_loss"] >= 0).all())
        self.assertTrue(scored["brier"].is_between(0, 2).all())

    def test_states_cover_every_race(self):
        counts = self.states.group_by("run", "model_key").agg(pl.col("state").n_unique())
        self.assertTrue((counts["state"] == 35).all())
        self.assertTrue(self.states["predicted_two_party"].is_between(0, 1).all())


if __name__ == "__main__":
    unittest.main()
