"""Turn each day's synthetic answers into a corrected Senate forecast with uncertainty.

The raw state share from a run is sum P(Democrat) / sum(P(Democrat) + P(Republican))
over the state's 100 sampled personas, so P(Would not vote) acts as a turnout
weight. The 2024 back-cast (src/validate_models.py) showed each model ranks
states well but spreads them too far from 50-50, so each model's share is
mapped through its fitted correction on the logit scale:

    corrected = intercept + slope * logit(raw share)

Workflow, per model and reporting day
-------------------------------------
1. Resample the 100 personas in every state with replacement (persona sampling).
2. Compute each state's raw share and apply the model's correction.
3. Add a national error shared by every state and an independent state error,
   both on the logit scale. The state SD is the model's back-cast residual SD.
   The national SD (NATIONAL_SD) is an assumption: one election cannot
   measure how far the whole country might swing.
4. Each draw gives every state's Democratic two-party share and a winner;
   adding the 65 seats not up in 2026 gives a 100-seat Senate.

The same draws are repeated DRAWS times. Nothing here queries a model: the
simulation reuses the saved answers. Each model/day has its own seed, so adding
a new day never changes earlier forecasts.

Outputs (data/forecast/): state_forecasts.parquet (one row per day x model x
state), seat_draws.parquet (one row per day x model x draw) and
seat_summary.parquet (one row per day x model).

Usage (repository root): uv run python src/forecast.py
The website build (src/prepare_website.py) calls add_corrected_forecasts()
directly, so every published day, including future daily runs, gets a forecast.
"""

from argparse import ArgumentParser
from pathlib import Path
import sys
import zlib

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # site_data imports src.helper_query_validation

DEFAULT_CORRECTIONS = ROOT / "data/model_validation/backcast_summary.parquet"
DEFAULT_OUTPUT_DIR = ROOT / "data/forecast"
DRAWS = 10_000
NATIONAL_SD = 0.10  # about 2.5 points near 50-50; an assumption, see the docstring
BASE_SEED = 2026
INTERVAL = (0.05, 0.95)  # 90 per cent intervals
MAJORITY = 51


def logistic(x):
    return 1 / (1 + np.exp(-x))


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def load_corrections(path=DEFAULT_CORRECTIONS):
    """Each model's intercept, slope and state SD from the 2024 back-cast."""
    rows = pl.read_parquet(path).select("model_key", "calibration_intercept", "calibration_slope",
                                        "calibration_residual_sd")
    return {row[0]: {"intercept": row[1], "slope": row[2], "state_sd": row[3]} for row in rows.rows()}


def seed_for(*parts):
    """A stable seed per model/day so earlier forecasts never change."""
    return np.random.default_rng([BASE_SEED, *(zlib.crc32(str(p).encode()) for p in parts)])


def simulate_states(rng, personas, draws=DRAWS, correction=None, national_sd=NATIONAL_SD, state_sd=None):
    """Draws of each state's Democratic two-party share.

    personas maps state -> (P(Democrat) array, P(Republican) array), one entry per
    sampled persona row. Without a correction the raw share is used and
    state_sd must be given. Returns (sorted states, draws x states array).
    """
    states = sorted(personas)
    if correction is not None:
        state_sd = correction["state_sd"]
    if state_sd is None:
        raise ValueError("Give a correction or a state SD.")
    shares = np.empty((draws, len(states)))
    for s, state in enumerate(states):
        dem, rep = (np.asarray(a, dtype=float) for a in personas[state])
        if dem.size == 0 or dem.size != rep.size:
            raise ValueError(f"{state}: no answers, or mismatched Democrat/Republican arrays.")
        pick = rng.integers(0, dem.size, size=(draws, dem.size))
        total = (dem[pick] + rep[pick]).sum(axis=1)
        if (total <= 0).any():
            raise ValueError(f"{state}: no two-party probability to share.")
        shares[:, s] = dem[pick].sum(axis=1) / total
    z = logit(shares)
    if correction is not None:
        z = correction["intercept"] + correction["slope"] * z
    z += rng.normal(0, national_sd, (draws, 1)) + rng.normal(0, state_sd, (draws, len(states)))
    return states, logistic(z)


def seat_totals(shares, fixed_seats):
    """Seats per draw: fixed seats plus states with a Democratic share above 50%."""
    dem_wins = (shares > 0.5).sum(axis=1)
    return {"democratic_seats": fixed_seats["democrat"] + dem_wins,
            "republican_seats": fixed_seats["republican"] + shares.shape[1] - dem_wins,
            "independent_seats": np.full(shares.shape[0], fixed_seats["independent"])}


def summarise(states, shares, seats, personas, correction=None):
    """State shares, intervals and win chances; seat median, interval and control."""
    low, high = INTERVAL
    state_rows = {}
    for s, state in enumerate(states):
        dem, rep = (np.asarray(a, dtype=float) for a in personas[state])
        raw = dem.sum() / (dem + rep).sum()
        point = (logistic(correction["intercept"] + correction["slope"] * logit(raw))
                 if correction is not None else raw)
        state_rows[state] = {"raw_share": float(raw), "corrected_share": float(point),
                             "median": float(np.median(shares[:, s])),
                             "low": float(np.quantile(shares[:, s], low)),
                             "high": float(np.quantile(shares[:, s], high)),
                             "dem_win_chance": float((shares[:, s] > 0.5).mean())}
    dem = seats["democratic_seats"]
    rep = seats["republican_seats"]
    counts = np.bincount(dem, minlength=101)
    seat_summary = {"draws": int(dem.size), "median": int(np.median(dem)),
                    "low": int(np.quantile(dem, low)), "high": int(np.quantile(dem, high)),
                    "democratic_majority": float((dem >= MAJORITY).mean()),
                    "republican_majority": float((rep >= MAJORITY).mean()),
                    "independent_seats": int(seats["independent_seats"][0]),
                    "histogram": {str(k): int(v) for k, v in enumerate(counts) if v}}
    seat_summary["no_majority"] = 1 - seat_summary["democratic_majority"] - seat_summary["republican_majority"]
    return state_rows, seat_summary


def forecast_entry(entry, key, day, correction, fixed_seats, draws=DRAWS, national_sd=NATIONAL_SD):
    """Corrected forecast for one website snapshot entry (one model, one day)."""
    personas = {state: ([p["p_democrat"] for p in values["points"]],
                        [p["p_republican"] for p in values["points"]])
                for state, values in entry["states"].items()}
    rng = seed_for(day, key)
    states, shares = simulate_states(rng, personas, draws, correction, national_sd)
    seats = seat_totals(shares, fixed_seats)
    state_rows, seat_summary = summarise(states, shares, seats, personas, correction)
    return {"states": state_rows, "seats": seat_summary, "national_sd": national_sd,
            "state_sd": correction["state_sd"], "intercept": correction["intercept"],
            "slope": correction["slope"]}, seats


def add_corrected_forecasts(history, root=ROOT, draws=DRAWS, keep_draws=False):
    """Attach entry['forecast'] to every complete synthetic model/day in history.

    External benchmarks and models without a back-cast correction are skipped
    (their 'forecast' is None). With keep_draws, seat draws are kept under
    history['seat_draws'][(day, key)] for saving as Parquet.
    """
    corrections = load_corrections(root / "data/model_validation/backcast_summary.parquet")
    fixed = history["baseline"]["fixed_seats"]
    history["forecast_settings"] = {"draws": draws, "national_sd": NATIONAL_SD, "interval": list(INTERVAL)}
    if keep_draws:
        history["seat_draws"] = {}
    for day, snapshot in history["snapshots"].items():
        for key, entry in snapshot["models"].items():
            entry["forecast"] = None
            if entry.get("kind") == "external_forecast" or not entry.get("complete") or key not in corrections:
                continue
            entry["forecast"], seats = forecast_entry(entry, key, day, corrections[key], fixed, draws)
            if keep_draws:
                history["seat_draws"][(day, key)] = seats
    return history


def forecast_tables(history):
    """Parquet-ready tables from a history with corrected forecasts."""
    state_rows, seat_rows, draw_frames = [], [], []
    for day, snapshot in sorted(history["snapshots"].items()):
        for key, entry in snapshot["models"].items():
            forecast = entry.get("forecast")
            if not forecast:
                continue
            for state, values in forecast["states"].items():
                state_rows.append({"date": day, "model_key": key, "state": history["states"][state]["name"],
                                   **values})
            seats = forecast["seats"]
            seat_rows.append({"date": day, "model_key": key, "run": entry["run"],
                              **{k: v for k, v in seats.items() if k != "histogram"},
                              "national_sd": forecast["national_sd"], "state_sd": forecast["state_sd"],
                              "intercept": forecast["intercept"], "slope": forecast["slope"]})
            draws = history.get("seat_draws", {}).get((day, key))
            if draws is not None:
                draw_frames.append(pl.DataFrame({"date": day, "model_key": key,
                                                 "draw": np.arange(len(draws["democratic_seats"])),
                                                 **draws}))
    return (pl.DataFrame(state_rows).sort("date", "model_key", "state"),
            pl.DataFrame(seat_rows).sort("date", "model_key"),
            pl.concat(draw_frames) if draw_frames else None)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--draws", type=int, default=DRAWS)
    args = parser.parse_args()

    from site_data import load_history  # same run discovery and checks as the website
    history = add_corrected_forecasts(load_history(ROOT), ROOT, args.draws, keep_draws=True)
    states, seats, draws = forecast_tables(history)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    states.write_parquet(out / "state_forecasts.parquet")
    seats.write_parquet(out / "seat_summary.parquet")
    draws.write_parquet(out / "seat_draws.parquet")
    with pl.Config(tbl_rows=-1, tbl_cols=-1, tbl_width_chars=160, float_precision=3):
        print(seats.select("date", "model_key", "median", "low", "high", "democratic_majority",
                           "republican_majority"))
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
