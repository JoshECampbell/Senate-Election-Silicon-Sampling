"""Tests run against the saved simulated study in data/simulated/ and the
forecast function that produced it.

- Frame: 17,000 respondents in all 50 states and DC; variables are linked the
  way they are in real survey data (party ID drives vote and ideology, Black
  respondents lean Democratic, Wyoming is more Republican than Massachusetts,
  unregistered people mostly did not vote) and pid3 agrees with pid7.
- Personas: 100 rows per Senate state, every persona is a frame respondent from
  that state, and the draws follow the survey weights.
- Responses: one row per run day x model x persona row; valid rows have four
  probabilities in [0, 1] that sum to 1; invalid rows have all four null and a
  recorded reason; a respondent drawn twice gets the same answer; failures stay
  rare; the persona's state still shows through the answers.
- Forecast: shares in (0, 1) with no nulls; winners agree with shares; every
  draw covers 35 states and 100 seats; seat totals agree with state winners;
  the seat distribution has spread; safe states stay safe.
- Forecast function: NA and invalid answers are excluded rather than averaged,
  P(Would not vote) acts as a turnout weight, missing states raise an error and
  the result is reproducible from a seed.

Usage: uv run python -m unittest discover -s test -p 'test_simulated_pipeline.py' -v
Generate the data first with: uv run python src/simulate_data.py
"""

from pathlib import Path
import math
import sys
import unittest

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from create_personas import SENATE_STATES_2026
from simulate_data import MODELS, P_COLUMNS, RUN_DATES, fixed_seats, forecast_draws

SIMULATED = ROOT / "data/simulated"
STATE_NAMES = sorted(SENATE_STATES_2026.values())


def weighted_share(frame, condition):
    """Weighted share of rows meeting a condition."""
    return frame.select((condition.cast(pl.Float64) * pl.col("commonweight")).sum()
                        / pl.col("commonweight").sum()).item()


class SimulatedFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = pl.read_parquet(SIMULATED / "cleaned_CES_data.parquet")

    def test_size_and_coverage(self):
        self.assertEqual(self.frame.height, 17_000)
        self.assertEqual(self.frame["inputstate"].n_unique(), 51, "Expected 50 states and DC.")
        counts = self.frame.group_by("inputstate").len()
        senate = counts.filter(pl.col("inputstate").is_in(list(SENATE_STATES_2026)))
        self.assertEqual(senate.height, 35)
        self.assertGreaterEqual(senate["len"].min(), 10, "Every Senate state needs respondents.")

    def test_weights_average_one(self):
        self.assertAlmostEqual(self.frame["commonweight"].mean(), 1.0, places=6)

    def test_party_id_drives_2024_vote(self):
        voters = self.frame.filter(pl.col("presvote24post").is_in([1, 2]))
        strong_dem = voters.filter(pl.col("pid7") == 1)
        strong_rep = voters.filter(pl.col("pid7") == 7)
        self.assertGreater(weighted_share(strong_dem, pl.col("presvote24post") == 1), 0.85)
        self.assertGreater(weighted_share(strong_rep, pl.col("presvote24post") == 2), 0.85)

    def test_ideology_follows_party_id(self):
        answered = self.frame.filter(pl.col("pid7") <= 7, pl.col("ideo5") <= 5)
        correlation = answered.select(pl.corr("pid7", "ideo5")).item()
        self.assertGreater(correlation, 0.5)

    def test_race_and_state_shape_party(self):
        democrat = pl.col("pid7") <= 3
        black = weighted_share(self.frame.filter(pl.col("race") == 2), democrat)
        white = weighted_share(self.frame.filter(pl.col("race") == 1), democrat)
        self.assertGreater(black, white + 0.2)
        massachusetts = weighted_share(self.frame.filter(pl.col("inputstate") == 25), democrat)
        wyoming = weighted_share(self.frame.filter(pl.col("inputstate") == 56), democrat)
        self.assertGreater(massachusetts, wyoming)

    def test_unregistered_mostly_did_not_vote(self):
        unregistered = self.frame.filter(pl.col("votereg") != 1, pl.col("presvote24post").is_not_null())
        self.assertGreater(weighted_share(unregistered, pl.col("presvote24post") == 9), 0.8)

    def test_pid3_agrees_with_pid7(self):
        expected = {1: {1}, 2: {1}, 3: {3}, 4: {3, 4}, 5: {3}, 6: {2}, 7: {2}, 8: {5}}
        pairs = self.frame.select("pid7", "pid3").unique().rows()
        for pid7, pid3 in pairs:
            self.assertIn(pid3, expected[pid7], f"pid7={pid7} paired with pid3={pid3}.")


class SimulatedPersonaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = pl.read_parquet(SIMULATED / "cleaned_CES_data.parquet")
        cls.personas = pl.read_parquet(SIMULATED / "personas.parquet")

    def test_one_hundred_rows_per_senate_state(self):
        counts = self.personas.group_by("state").len()
        self.assertEqual(sorted(counts["state"]), STATE_NAMES)
        self.assertTrue((counts["len"] == 100).all())
        rows = self.personas.group_by("state").agg(pl.col("persona_row").sort())
        for row in rows["persona_row"]:
            self.assertEqual(row.to_list(), list(range(100)))

    def test_personas_come_from_their_own_state(self):
        codes = {name: code for code, name in SENATE_STATES_2026.items()}
        self.assertTrue((self.personas["inputstate"]
                         == self.personas["state"].replace_strict(codes)).all())
        missing = self.personas.join(self.frame, on="caseid", how="anti")
        self.assertEqual(missing.height, 0, "Every persona must be a frame respondent.")

    def test_draws_follow_weights(self):
        # Respondents with above-median weight should be drawn more often.
        joined = self.frame.join(self.personas.group_by("caseid").len(), on="caseid", how="left")
        joined = joined.filter(pl.col("inputstate").is_in(list(SENATE_STATES_2026)))
        joined = joined.with_columns(pl.col("len").fill_null(0))
        heavy = joined.filter(pl.col("commonweight") > pl.col("commonweight").median())
        light = joined.filter(pl.col("commonweight") <= pl.col("commonweight").median())
        self.assertGreater(heavy["len"].mean(), light["len"].mean())


class SimulatedResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.responses = pl.read_parquet(SIMULATED / "responses.parquet")

    def test_one_row_per_run_model_and_persona(self):
        expected = len(RUN_DATES) * len(MODELS) * 35 * 100
        self.assertEqual(self.responses.height, expected)
        keys = ["run_date", "model_key", "state", "persona_row"]
        self.assertEqual(self.responses.select(keys).unique().height, expected)

    def test_valid_rows_are_probability_vectors(self):
        valid = self.responses.filter(pl.col("probability_valid"))
        self.assertEqual(valid.select(pl.col(P_COLUMNS).null_count()).sum_horizontal().item(), 0)
        for column in P_COLUMNS:
            self.assertTrue(valid[column].is_between(0, 1).all(), f"{column} outside [0, 1].")
        totals = valid.select(pl.sum_horizontal(P_COLUMNS)).to_series()
        self.assertTrue(((totals - 1).abs() <= 1e-6).all(), "Probabilities must sum to 1.")
        self.assertTrue((valid["status"] == "ok").all())

    def test_invalid_rows_are_null_and_explained(self):
        invalid = self.responses.filter(~pl.col("probability_valid"))
        self.assertGreater(invalid.height, 0, "The simulation should include failures to test.")
        self.assertTrue(invalid.select(pl.all_horizontal(pl.col(P_COLUMNS).is_null())).to_series().all())
        self.assertEqual(invalid["error"].null_count(), 0)
        self.assertEqual(set(invalid["status"]), {"refused", "error", "invalid"})

    def test_failures_are_rare_in_every_state(self):
        rates = (self.responses.group_by("run_date", "model_key", "state")
                 .agg((~pl.col("probability_valid")).mean().alias("rate")))
        self.assertLess(rates["rate"].max(), 0.15)

    def test_repeat_draws_share_one_answer(self):
        repeats = (self.responses.group_by("run_date", "model_key", "state", "caseid")
                   .agg(pl.col("p_democrat").n_unique().alias("answers"),
                        pl.col("status").n_unique().alias("statuses")))
        self.assertTrue((repeats["answers"] == 1).all())
        self.assertTrue((repeats["statuses"] == 1).all())

    def test_state_lean_reaches_the_answers(self):
        means = (self.responses.group_by("model_key", "state")
                 .agg(pl.col("p_democrat").mean()))
        for model in MODELS:
            ma = means.filter(model_key=model, state="Massachusetts")["p_democrat"].item()
            wy = means.filter(model_key=model, state="Wyoming")["p_democrat"].item()
            self.assertGreater(ma, wy, f"{model} should favour Democrats more in Massachusetts.")

    def test_costs_are_recorded(self):
        self.assertEqual(self.responses["cost_usd"].null_count(), 0)
        self.assertTrue((self.responses["cost_usd"] >= 0).all())
        self.assertTrue((self.responses["input_tokens"] > 0).all())


class SimulatedForecastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.states = pl.read_parquet(SIMULATED / "forecast_state_draws.parquet")
        cls.seats = pl.read_parquet(SIMULATED / "forecast_seat_draws.parquet")
        cls.fixed = fixed_seats()

    def test_shares_are_complete_and_bounded(self):
        share = self.states["dem_two_party_share"]
        self.assertEqual(share.null_count(), 0)
        self.assertFalse(share.is_nan().any())
        self.assertTrue(((share > 0) & (share < 1)).all())

    def test_winner_matches_share(self):
        expected = pl.when(pl.col("dem_two_party_share") > 0.5).then(pl.lit("Democrat")).otherwise(pl.lit("Republican"))
        self.assertTrue(self.states.select(pl.col("winner") == expected).to_series().all())

    def test_every_draw_covers_every_state(self):
        per_draw = self.states.group_by("model_key", "draw").agg(pl.col("state").sort())
        for states in per_draw["state"]:
            self.assertEqual(states.to_list(), STATE_NAMES)
        self.assertEqual(set(self.states["model_key"]), set(MODELS))

    def test_seats_add_to_one_hundred(self):
        total = self.seats.select(pl.sum_horizontal("democratic_seats", "republican_seats",
                                                    "independent_seats")).to_series()
        self.assertTrue((total == 100).all())
        self.assertTrue((self.seats["democratic_seats"] >= self.fixed["democrat"]).all())
        self.assertTrue((self.seats["republican_seats"] >= self.fixed["republican"]).all())
        self.assertTrue((self.seats["independent_seats"] == self.fixed["independent"]).all())

    def test_seats_agree_with_state_winners(self):
        wins = (self.states.group_by("model_key", "draw")
                .agg((pl.col("winner") == "Democrat").sum().alias("dem_wins")))
        joined = self.seats.join(wins, on=["model_key", "draw"])
        self.assertEqual(joined.height, self.seats.height)
        self.assertTrue((joined["democratic_seats"] == self.fixed["democrat"] + joined["dem_wins"]).all())

    def test_distribution_has_spread(self):
        spread = self.seats.group_by("model_key").agg(pl.col("democratic_seats").std())
        self.assertTrue((spread["democratic_seats"] > 0.5).all(), "Uncertainty collapsed to a point.")

    def test_safe_states_stay_safe(self):
        dem_wins = (self.states.group_by("model_key", "state")
                    .agg((pl.col("winner") == "Democrat").mean().alias("p")))
        for model in MODELS:
            self.assertGreater(dem_wins.filter(model_key=model, state="Massachusetts")["p"].item(), 0.95)
            self.assertLess(dem_wins.filter(model_key=model, state="Wyoming")["p"].item(), 0.05)


class ForecastFunctionTests(unittest.TestCase):
    """Hand-made inputs where the right answer is known."""

    FIXED = {"democrat": 32, "republican": 31, "independent": 2}

    def responses(self, rows):
        frame = pl.DataFrame(rows, schema={
            "run_date": pl.String, "model_key": pl.String, "state": pl.String,
            "p_democrat": pl.Float64, "p_republican": pl.Float64,
            "p_third_party": pl.Float64, "p_would_not_vote": pl.Float64,
            "probability_valid": pl.Boolean})
        return frame

    def row(self, state, dem, rep, valid=True, run="d1"):
        other = None if dem is None else (1 - dem - rep) / 2
        return {"run_date": run, "model_key": "m", "state": state, "p_democrat": dem,
                "p_republican": rep, "p_third_party": other, "p_would_not_vote": other,
                "probability_valid": valid}

    def test_invalid_answers_are_excluded(self):
        rows = [self.row("A", 0.6, 0.4)] * 10 + [self.row("A", None, None, valid=False)] * 5
        rows += [self.row("B", 0.3, 0.7)] * 10
        states, seats = forecast_draws(np.random.default_rng(1), self.responses(rows), self.FIXED,
                                       draws=50, national_sd=0, state_sd=0)
        self.assertEqual(states["dem_two_party_share"].null_count(), 0)
        a = states.filter(state="A")["dem_two_party_share"]
        self.assertTrue(((a - 0.6).abs() < 1e-9).all())
        self.assertTrue((seats["democratic_seats"] == 33).all())

    def test_nonvoting_acts_as_turnout_weight(self):
        # Person 1: likely voter for D. Person 2: probably stays home, leans R.
        rows = [self.row("A", 0.8, 0.2), self.row("A", 0.05, 0.15)]
        states, _ = forecast_draws(np.random.default_rng(2), self.responses(rows * 50), self.FIXED,
                                   draws=1, national_sd=0, state_sd=0)
        share = states["dem_two_party_share"].item()
        # With equal weight per person the share would be (0.8 + 0.25) / 2 = 0.525.
        self.assertTrue(math.isclose(share, 0.85 / 1.2, abs_tol=0.05))

    def test_state_with_no_valid_answers_raises(self):
        rows = [self.row("A", 0.6, 0.4), self.row("B", None, None, valid=False)]
        with self.assertRaises(ValueError):
            forecast_draws(np.random.default_rng(3), self.responses(rows), self.FIXED, draws=5)

    def test_same_seed_same_forecast(self):
        rows = [self.row("A", 0.5, 0.45), self.row("A", 0.4, 0.5), self.row("B", 0.55, 0.4)]
        first = forecast_draws(np.random.default_rng(7), self.responses(rows * 5), self.FIXED, draws=20)
        second = forecast_draws(np.random.default_rng(7), self.responses(rows * 5), self.FIXED, draws=20)
        self.assertTrue(first[0].equals(second[0]))
        self.assertTrue(first[1].equals(second[1]))


if __name__ == "__main__":
    unittest.main()
