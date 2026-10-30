"""Simulate the whole study before (and alongside) the real data: the CES frame,
the persona sample, the model responses and the Senate forecast.

Workflow
--------
1. Frame: simulate CES-like respondents in all 50 states and DC with the same 17
   columns, codes and storage types as data/cleaned/cleaned_CES_data.parquet.
   Variables are linked rather than drawn independently: state shapes race and
   religion; age shapes education, marriage and registration; race, education,
   religion, gender, age, sexuality and state together set a latent partisan
   lean that drives pid7, pid3, ideology, 2024 vote and 2026 House intention.
   Survey weights up-weight groups that online panels under-represent.
2. Sample: draw 100 personas per 2026 Senate state with replacement, with
   probability proportional to commonweight (the same rule as create_personas.py).
3. Responses: simulate the four probabilities that each decision model returns
   for each distinct respondent on each of three run days. A model only sees the
   9-characteristic persona (no party ID or ideology), so it predicts from
   demographics plus its own lean. Refusals, API errors and malformed vectors are
   injected on purpose and marked invalid by the project's real validation check.
4. Forecast: for each model, resample the 100 personas and pick one of the run
   days. Each draw gives every state's Democratic share of the two-party vote
   and a winner; adding the 65 seats not up in 2026 gives a seat count. This is
   the same bootstrap as the real forecast in forecast.py.

Outputs (data/simulated/)
-------------------------
  cleaned_CES_data.parquet      the simulated frame, same schema as the real file
  personas.parquet              100 rows per Senate state, plus persona_row
  responses.parquet             one row per run day x model x persona row
  forecast_state_draws.parquet  one row per model x draw x state
  forecast_seat_draws.parquet   one row per model x draw (seat totals)

Each stage gets its own random stream from one seed, so changing the number of
forecast draws does not change the simulated respondents.

Usage (repository root): uv run python src/simulate_data.py
Optional: --rows 17000 --draws 1000 --seed 2453 --output-dir data/simulated
"""

from argparse import ArgumentParser
from pathlib import Path
import sys

import numpy as np
import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from create_personas import SENATE_STATES_2026
from data_cleaning import CES_SCHEMA
from forecast import bootstrap_states, seat_totals
from helper_query_validation import probability_error

DEFAULT_OUTPUT_DIR = ROOT / "data/simulated"
SURVEY_YEAR = 2025
PERSONAS_PER_STATE = 100
RUN_DATES = ["2026-10-30", "2026-10-31", "2026-11-01"]
P_COLUMNS = ["p_democrat", "p_republican", "p_third_party", "p_would_not_vote"]

# ---------------------------------------------------------------------------
# State inputs: approximate 2024 population (millions) and approximate 2024
# presidential margin (Republican minus Democratic, percentage points). They only
# give the simulated states realistic sizes and leans; nothing is estimated
# from them. Keys are CES inputstate codes (FIPS).
# ---------------------------------------------------------------------------
STATES = {
    1: (5.16, 30.5), 2: (0.74, 13.1), 4: (7.58, 5.5), 5: (3.09, 30.6), 6: (39.43, -20.2),
    8: (5.96, -11.0), 9: (3.68, -14.5), 10: (1.05, -14.7), 11: (0.70, -83.0), 12: (23.37, 13.1),
    13: (11.18, 2.2), 15: (1.45, -23.1), 16: (2.00, 36.5), 17: (12.71, -10.9), 18: (6.92, 19.0),
    19: (3.24, 13.2), 20: (2.97, 16.1), 21: (4.59, 30.5), 22: (4.60, 22.0), 23: (1.41, -6.9),
    24: (6.26, -28.5), 25: (7.14, -25.2), 26: (10.14, 1.4), 27: (5.79, -4.2), 28: (2.94, 22.9),
    29: (6.25, 18.4), 30: (1.14, 20.1), 31: (2.01, 20.5), 32: (3.27, 3.1), 33: (1.41, -2.8),
    34: (9.50, -5.9), 35: (2.13, -6.0), 36: (19.87, -12.6), 37: (11.05, 3.2), 38: (0.80, 36.5),
    39: (11.88, 11.2), 40: (4.10, 34.3), 41: (4.27, -14.3), 42: (13.08, 1.7), 44: (1.11, -13.8),
    45: (5.48, 18.2), 46: (0.92, 29.2), 47: (7.23, 29.7), 48: (31.29, 13.7), 49: (3.50, 21.6),
    50: (0.65, -31.5), 51: (8.81, -5.8), 53: (7.96, -18.2), 54: (1.77, 41.9), 55: (5.96, 0.9),
    56: (0.59, 45.8),
}

# Race codes: 1 White, 2 Black, 3 Hispanic, 4 Asian, 5 Native American,
# 6 Two or more, 7 Other, 8 Middle Eastern. White takes whatever share remains.
RACE_DEFAULT = {2: 0.08, 3: 0.10, 4: 0.04, 5: 0.01, 6: 0.03, 7: 0.01, 8: 0.01}
RACE_BY_STATE = {
    1: {2: 0.26}, 2: {5: 0.14, 4: 0.07}, 4: {3: 0.32}, 6: {3: 0.40, 4: 0.15}, 8: {3: 0.22},
    10: {2: 0.22}, 11: {2: 0.44, 3: 0.12}, 12: {2: 0.15, 3: 0.27}, 13: {2: 0.31},
    15: {4: 0.37, 2: 0.02}, 17: {2: 0.14, 3: 0.18}, 22: {2: 0.31}, 24: {2: 0.30},
    26: {2: 0.13}, 28: {2: 0.37}, 30: {5: 0.06, 2: 0.01}, 32: {3: 0.30, 4: 0.09},
    34: {3: 0.22, 4: 0.10, 2: 0.13}, 35: {3: 0.48, 5: 0.09, 2: 0.02}, 36: {2: 0.15, 3: 0.19, 4: 0.09},
    37: {2: 0.21}, 40: {5: 0.08}, 45: {2: 0.25}, 46: {5: 0.08, 2: 0.02}, 47: {2: 0.16},
    48: {3: 0.40, 2: 0.12}, 51: {2: 0.19}, 53: {4: 0.10},
    # Low-diversity states.
    16: {2: 0.01, 3: 0.12}, 19: {2: 0.04, 3: 0.06}, 23: {2: 0.02, 3: 0.02},
    33: {2: 0.02, 3: 0.04}, 38: {2: 0.03, 3: 0.04, 5: 0.05}, 49: {2: 0.01, 3: 0.15},
    50: {2: 0.01, 3: 0.02}, 54: {2: 0.04, 3: 0.02}, 56: {2: 0.01, 3: 0.10, 5: 0.03},
}

# Effects on the latent partisan lean (positive = Republican). Shared by the
# frame generator and the model-response simulator.
RACE_LEAN = {1: 0.35, 2: -1.40, 3: -0.35, 4: -0.50, 5: 0.0, 6: -0.20, 7: 0.0, 8: -0.20}
RELIGION_LEAN = {1: 0.35, 2: 0.10, 3: 0.80, 4: 0.0, 5: -0.60, 6: -0.40, 7: -0.40, 8: -0.40,
                 9: -0.90, 10: -0.80, 11: -0.35, 12: 0.0}
EDUCATION_LEAN = {1: 0.15, 2: 0.15, 3: 0.05, 4: 0.0, 5: -0.20, 6: -0.45}

# Target national shares used to place the ordinal cut points.
PID7_SHARES = [0.22, 0.11, 0.07, 0.18, 0.08, 0.10, 0.24]          # codes 1-7
IDEO5_SHARES = [0.12, 0.18, 0.34, 0.22, 0.14]                     # codes 1-5
EDUCATION_CUTS = [-1.405, -0.358, 0.151, 0.412, 1.126]            # normal quantiles


# ---------------------------------------------------------------------------
# Decision models: how each simulated model turns a persona into probabilities.
# lean_scale: how strongly demographics move the answer; bias: shift toward
# Republican (+) or Democrat (-); third/nonvote: baseline utilities; noise: SD
# of per-call randomness; day_sd: SD of the shift between run days.
# ---------------------------------------------------------------------------
MODELS = {
    "jev": dict(model="typesafe/jev-1.13", lean_scale=1.0, bias=0.15, third=-3.0, nonvote=-1.3,
                noise=0.5, day_sd=0.05, refusal=0.01, cost=0.000019),
    "mercury": dict(model="inception/mercury-decide", lean_scale=1.2, bias=0.10, third=-3.2,
                    nonvote=-1.1, noise=0.5, day_sd=0.05, refusal=0.02, cost=0.0),
    "decider": dict(model="perplexity/pplx-decider-v1.2", lean_scale=0.8, bias=-0.25, third=-2.0,
                    nonvote=-1.0, noise=0.6, day_sd=0.08, refusal=0.01, cost=0.000004),
}
ERROR_RATE = 0.005       # API errors per call, on top of each model's refusal rate
MALFORMED_RATE = 0.005   # "ok" responses whose probabilities fail validation



def categorical(rng, probs):
    """Draw one column index per row of a (rows x options) probability matrix."""
    cumulative = probs.cumsum(axis=1) / probs.sum(axis=1, keepdims=True)
    picks = (cumulative < rng.random((probs.shape[0], 1))).sum(axis=1)
    return np.minimum(picks, probs.shape[1] - 1)


def logistic(x):
    return 1 / (1 + np.exp(-x))


def demographic_lean(frame):
    """Partisan lean implied by demographics alone (positive = Republican).

    This is the part of each person's lean that a model can infer from a
    9-characteristic persona. Education and religion matter more for White
    respondents, which mirrors the education and evangelical gaps.
    """
    margin = frame["inputstate"].replace_strict({k: v[1] for k, v in STATES.items()}, default=0.0)
    white = (frame["race"] == 1).cast(pl.Float64)
    lean = (
        margin.cast(pl.Float64) / 50
        + frame["race"].replace_strict(RACE_LEAN, default=0.0)
        + frame["educ"].replace_strict(EDUCATION_LEAN, default=0.0) * (0.5 + white)
        + frame["religpew"].replace_strict(RELIGION_LEAN, default=0.0).fill_null(0.0)
        + 0.35 * white * (frame["religpew"] == 1).cast(pl.Float64).fill_null(0.0)
        - 0.20 * (frame["gender4"] == 2).cast(pl.Float64)
        - 1.00 * (frame["gender4"] == 3).cast(pl.Float64)
        - 0.80 * frame["sexuality"].is_in([2, 3, 4]).cast(pl.Float64).fill_null(0.0)
    )
    return lean.to_numpy()


# ---------------------------------------------------------------------------
# 1. Frame
# ---------------------------------------------------------------------------
def simulate_frame(rng, rows=17_000):
    """Simulate CES-like respondents with linked variables and survey weights."""
    if rows < 1:
        raise ValueError("Choose at least one simulated row.")
    codes = np.array(list(STATES))
    population = np.array([v[0] for v in STATES.values()])
    state = rng.choice(codes, size=rows, p=population / population.sum())

    # Race depends on state.
    race_table = np.zeros((len(codes), 8))
    for i, code in enumerate(codes):
        shares = {**RACE_DEFAULT, **RACE_BY_STATE.get(code, {})}
        shares[1] = 1 - sum(shares.values())
        race_table[i] = [shares[r] for r in range(1, 9)]
    state_index = np.searchsorted(codes, state)
    race = categorical(rng, race_table[state_index]) + 1

    gender = rng.choice([1, 2, 3, 4], size=rows, p=[0.47, 0.51, 0.01, 0.01])

    # Age groups 18-29, 30-44, 45-64, 65+; exact age within each group.
    age_group = rng.choice(4, size=rows, p=[0.20, 0.25, 0.33, 0.22])
    low, high = np.array([18, 30, 45, 65]), np.array([29, 44, 64, 90])
    age = rng.integers(low[age_group], high[age_group] + 1)
    birthyr = SURVEY_YEAR - age

    # Education rises with age to mid-life and differs by race; 18-21 year olds
    # are too young for most degrees.
    latent = (rng.normal(size=rows) + 0.6 * (race == 4) - 0.35 * np.isin(race, [2, 3])
              + 0.15 * np.isin(age_group, [1, 2]) - 0.8 * (age < 22))
    educ = np.searchsorted(EDUCATION_CUTS, latent) + 1

    # Marital status depends on age group.
    marital_table = np.array([
        [0.20, 0.01, 0.02, 0.00, 0.70, 0.07],
        [0.55, 0.02, 0.08, 0.01, 0.29, 0.05],
        [0.60, 0.02, 0.15, 0.04, 0.15, 0.04],
        [0.55, 0.01, 0.15, 0.22, 0.05, 0.02],
    ])
    marstat = categorical(rng, marital_table[age_group]) + 1

    # Income rises with education and marriage; 4 per cent prefer not to say.
    latent = 0.55 * (educ - 3.5) / 1.4 + 0.25 * (marstat == 1) + rng.normal(0, 0.85, rows)
    faminc = np.clip(np.round(7.5 + 3.0 * latent), 1, 16).astype(int)
    faminc[rng.random(rows) < 0.04] = 97

    # Religion depends on race, age and state.
    religion = np.tile([0.36, 0.20, 0.01, 0.005, 0.02, 0.01, 0.01, 0.01, 0.06, 0.06, 0.20, 0.065],
                       (rows, 1))
    religion[race == 2, 0] *= 2.2                       # Black Protestants
    religion[race == 3, 1] *= 2.5                       # Hispanic Catholics
    religion[race == 4] *= [1, 1, 1, 1, 1, 1, 6, 6, 1, 1, 1, 1]
    religion[age < 30] *= [0.7, 0.8, 1, 1, 1, 1, 1, 1, 1.6, 1.6, 1.5, 1]
    religion[state == 49, 2] *= 50                      # Utah
    religion[state == 16, 2] *= 20                      # Idaho
    margin = np.array([STATES[s][1] for s in state])
    religion[:, 0] *= 1 + np.clip(margin, -30, 40) / 100  # more Protestant in Republican states
    religpew = categorical(rng, religion) + 1

    # Younger people more often identify as bisexual.
    sexuality_table = np.array([[0.80, 0.015, 0.02, 0.12, 0.015, 0.03],
                                [0.89, 0.015, 0.02, 0.04, 0.01, 0.025]])
    sexuality = categorical(rng, sexuality_table[(age >= 30).astype(int)]) + 1

    frame = pl.DataFrame({"race": race, "gender4": gender, "inputstate": state, "educ": educ,
                          "religpew": religpew, "sexuality": sexuality})

    # Partisan lean: demographics plus age, income and individual variation.
    lean = (demographic_lean(frame) - 0.35 * (age < 30) + 0.10 * (age >= 65)
            + 0.03 * np.where(faminc == 97, 7.5, faminc) - 0.2 + rng.normal(0, 0.9, rows))
    pid7 = np.searchsorted(np.quantile(lean, np.cumsum(PID7_SHARES)[:-1]), lean) + 1
    unsure = rng.random(rows) < 0.03 + 0.04 * (educ <= 2)
    pid7[unsure] = 8
    # Check "Not sure" (8) first: it would otherwise match pid7 >= 6.
    pid3 = np.select([pid7 == 8, pid7 <= 2, pid7 >= 6], [5, 1, 2], default=3)
    pid3[(pid7 == 4) & (rng.random(rows) < 0.15)] = 4

    # Ideology follows the same lean, with its own noise.
    ideology = lean + rng.normal(0, 0.6, rows)
    ideo5 = np.searchsorted(np.quantile(ideology, np.cumsum(IDEO5_SHARES)[:-1]), ideology) + 1
    ideo5[rng.random(rows) < 0.03 + 0.05 * (pid7 == 8)] = 6

    # Registration rises with age and education.
    registered = rng.random(rows) < logistic(1.4 + 0.35 * (educ - 3) + 0.6 * (age >= 45)
                                             - 0.5 * (age < 25))
    votereg = np.where(registered, 1, np.where(rng.random(rows) < 0.8, 2, 3))

    # 2024 vote: turnout depends on registration, age, education and how
    # partisan someone is; vote choice depends on the lean.
    strength = np.abs(lean - np.median(lean))
    turnout = np.where(registered,
                       logistic(0.8 + 0.3 * (educ - 3) + 0.5 * (age >= 45) + 0.4 * strength),
                       0.05)
    voted = rng.random(rows) < turnout
    centred = (lean - np.median(lean)) / lean.std()
    harris = rng.random(rows) < logistic(-2.2 * centred)
    presvote = np.where(harris, 1, 2)
    third = rng.random(rows) < 0.03
    presvote[third] = rng.choice([3, 4, 5, 6, 8], size=third.sum())
    presvote[~voted] = 9

    # 2026 House intention: 2024 voters mostly intend to vote again; people who
    # sat out 2024 mostly do not. Weak partisans are more often "Not sure".
    intends = rng.random(rows) < np.where(voted, 0.92, 0.35)
    house = np.where(rng.random(rows) < logistic(-2.0 * centred), 2, 3)
    house[rng.random(rows) < 0.12 * np.exp(-strength)] = 4
    house[~intends] = 1

    # Weights correct for groups the online panel under-represents.
    weight = (np.exp(rng.normal(0, 0.45, rows)) * np.where(age < 30, 1.4, 1.0)
              * np.where(educ <= 2, 1.3, 1.0) * np.where(race == 3, 1.2, 1.0))
    weight = weight / weight.mean()

    frame = frame.with_columns(
        pl.Series("caseid", np.arange(1, rows + 1, dtype=float)),
        pl.Series("marstat", marstat), pl.Series("faminc_new", faminc),
        pl.Series("birthyr", birthyr), pl.Series("votereg", votereg),
        pl.Series("pid3", pid3), pl.Series("pid7", pid7), pl.Series("ideo5", ideo5),
        pl.Series("CC25_363", house), pl.Series("presvote24post", presvote),
        pl.Series("commonweight", weight),
    )
    # The real cleaned export has genuine nulls in these columns.
    frame = frame.with_columns(
        pl.when(pl.lit(pl.Series(rng.random(rows) < 0.015))).then(None)
        .otherwise(pl.col(column)).alias(column)
        for column in ("religpew", "marstat", "sexuality", "faminc_new", "ideo5",
                       "CC25_363", "presvote24post")
    )
    return frame.select(list(CES_SCHEMA)).cast(CES_SCHEMA)


# ---------------------------------------------------------------------------
# 2. Sample
# ---------------------------------------------------------------------------
def draw_personas(rng, frame, per_state=PERSONAS_PER_STATE):
    """Weighted draws with replacement within each Senate state."""
    states = []
    for code, name in SENATE_STATES_2026.items():
        state_frame = frame.filter(pl.col("inputstate") == code)
        if state_frame.height == 0:
            raise ValueError(f"No simulated respondents in {name}.")
        weights = state_frame["commonweight"].to_numpy()
        rows = rng.choice(state_frame.height, size=per_state, replace=True, p=weights / weights.sum())
        states.append(state_frame[rows].with_columns(pl.lit(name).alias("state"),
                                                     pl.Series("persona_row", np.arange(per_state))))
    return pl.concat(states)


# ---------------------------------------------------------------------------
# 3. Responses
# ---------------------------------------------------------------------------
def corrupt(rng, probs):
    """Turn a valid vector into one of the failure shapes seen from real APIs."""
    kind = rng.integers(3)
    if kind == 0:
        return list(np.array(probs) * 1.2)            # sums to 1.2
    if kind == 1:
        return [float("nan"), *probs[1:]]             # missing number
    return [-0.1, probs[1] + probs[0] + 0.1, *probs[2:]]  # negative value


def simulate_responses(rng, personas, run_dates=RUN_DATES, models=MODELS):
    """Simulate each model's answer for each distinct respondent and run day.

    Like the real runner, a respondent drawn several times is asked once and the
    answer is copied to each of their persona rows. Invalid answers keep a row
    (so they stay visible) but all four probabilities are null.
    """
    unique = personas.unique(["state", "caseid"], maintain_order=True)
    lean = demographic_lean(unique)
    unregistered = (unique["votereg"] != 1).to_numpy()
    n = unique.height
    frames = []
    for run_date in run_dates:
        for key, spec in models.items():
            day_shift = rng.normal(0, spec["day_sd"])
            utility = np.column_stack([
                -spec["lean_scale"] * lean - spec["bias"] - day_shift,
                spec["lean_scale"] * lean + spec["bias"] + day_shift,
                np.full(n, spec["third"]),
                spec["nonvote"] + 1.8 * unregistered,
            ]) + rng.normal(0, spec["noise"], (n, 4))
            probs = np.exp(utility)
            probs /= probs.sum(axis=1, keepdims=True)

            outcome = rng.random(n)
            records = []
            for i in range(n):
                record = {"status": "ok", **dict(zip(P_COLUMNS, probs[i].tolist()))}
                if outcome[i] < spec["refusal"]:
                    record = {"status": "refused", **dict.fromkeys(P_COLUMNS)}
                elif outcome[i] < spec["refusal"] + ERROR_RATE:
                    record = {"status": "error", **dict.fromkeys(P_COLUMNS)}
                elif outcome[i] < spec["refusal"] + ERROR_RATE + MALFORMED_RATE:
                    record.update(zip(P_COLUMNS, corrupt(rng, probs[i].tolist())))
                # Same rule as query_llms.write_results: invalid vectors become null.
                error = probability_error(record, P_COLUMNS)
                record["probability_valid"] = error is None
                record["error"] = error
                if error:
                    record["status"] = "invalid" if record["status"] == "ok" else record["status"]
                    record.update(dict.fromkeys(P_COLUMNS))
                records.append(record)
            answers = pl.DataFrame(records, schema={"status": pl.String, **dict.fromkeys(P_COLUMNS, pl.Float64),
                                                    "probability_valid": pl.Boolean, "error": pl.String})
            answers = answers.with_columns(
                unique["state"], unique["caseid"],
                pl.lit(run_date).alias("run_date"), pl.lit(key).alias("model_key"),
                pl.lit(spec["model"]).alias("model"),
                pl.lit(spec["cost"]).alias("cost_usd"),
                pl.Series("input_tokens", rng.integers(150, 230, n)),
            )
            frames.append(personas.select("state", "persona_row", "caseid")
                          .join(answers, on=["state", "caseid"], how="left"))
    columns = ["run_date", "model_key", "model", "state", "persona_row", "caseid", "status",
               *P_COLUMNS, "probability_valid", "error", "cost_usd", "input_tokens"]
    return pl.concat(frames).select(columns).sort("run_date", "model_key", "state", "persona_row")


# ---------------------------------------------------------------------------
# 4. Forecast
# ---------------------------------------------------------------------------
def forecast_draws(rng, responses, fixed_seats, draws=1000):
    """Turn per-persona probabilities into draws of state results and seats.

    Uses the same bootstrap as the real forecast (forecast.bootstrap_states),
    plus a random run day per draw. Only valid rows are used, so a refusal or
    malformed answer can never put an NA into a share.
    """
    valid = responses.filter(pl.col("probability_valid"))
    states = sorted(responses["state"].unique())
    state_rows, seat_rows = [], []
    for model in sorted(responses["model_key"].unique()):
        model_rows = valid.filter(pl.col("model_key") == model)
        runs = sorted(model_rows["run_date"].unique())
        by_run = np.empty((len(runs), draws, len(states)))
        for r, run in enumerate(runs):
            personas = {}
            for state in states:
                rows = model_rows.filter((pl.col("run_date") == run) & (pl.col("state") == state))
                if rows.height == 0:
                    raise ValueError(f"{model} has no valid answers for {state} on {run}.")
                personas[state] = (rows["p_democrat"].to_numpy(), rows["p_republican"].to_numpy())
            _, by_run[r] = bootstrap_states(rng, personas, draws)
        share = by_run[rng.integers(0, len(runs), draws), np.arange(draws)]
        seats = seat_totals(share, fixed_seats)

        state_rows.append(pl.DataFrame({
            "model_key": model,
            "draw": np.repeat(np.arange(draws), len(states)),
            "state": np.tile(states, draws),
            "dem_two_party_share": share.ravel(),
            "winner": np.where(share.ravel() > 0.5, "Democrat", "Republican"),
        }))
        seat_rows.append(pl.DataFrame({"model_key": model, "draw": np.arange(draws), **seats}))
    return pl.concat(state_rows), pl.concat(seat_rows)


def fixed_seats():
    """Seats not up in 2026, from the same baseline the website uses."""
    config = yaml.safe_load((ROOT / "docs/site-config.yml").read_text())
    return config["baseline"]["fixed_seats"]


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=17_000)
    parser.add_argument("--draws", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2453)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    frame_rng, persona_rng, response_rng, forecast_rng = (
        np.random.default_rng(s) for s in np.random.SeedSequence(args.seed).spawn(4))
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    frame = simulate_frame(frame_rng, args.rows)
    frame.write_parquet(out / "cleaned_CES_data.parquet")
    personas = draw_personas(persona_rng, frame)
    personas.write_parquet(out / "personas.parquet")
    responses = simulate_responses(response_rng, personas)
    responses.write_parquet(out / "responses.parquet")
    state_draws, seat_draws = forecast_draws(forecast_rng, responses, fixed_seats(), args.draws)
    state_draws.write_parquet(out / "forecast_state_draws.parquet")
    seat_draws.write_parquet(out / "forecast_seat_draws.parquet")

    invalid = (~responses["probability_valid"]).sum()
    print(f"Frame: {frame.height:,} respondents. Personas: {personas.height:,} rows.")
    print(f"Responses: {responses.height:,} rows, {invalid:,} invalid and excluded.")
    print(seat_draws.group_by("model_key").agg(
        pl.col("democratic_seats").median().alias("median_dem_seats"),
        pl.col("democratic_seats").quantile(0.05).alias("p05"),
        pl.col("democratic_seats").quantile(0.95).alias("p95"),
    ).sort("model_key"))
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
