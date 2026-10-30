"""Turn each day's synthetic answers into a Senate forecast with bootstrap ranges.

A state's share is sum P(Democrat) / sum(P(Democrat) + P(Republican)) over its 100
sampled personas, so P(Would not vote) acts as a turnout weight.

Workflow, per model and reporting day
-------------------------------------
1. Resample the 100 personas in every state with replacement.
2. Recompute each state's Democratic two-party share and its winner.
3. Add the 65 seats not up in 2026 to get a 100-seat Senate.
4. Repeat DRAWS times, then summarise the shares and seat totals.

The bootstrap measures one source of uncertainty: having only 100 personas per
state. It does not measure model error, a national swing or anything else about
the election. The 2024 back-cast (src/validate_models.py) shows the models
spread states too far from 50-50, so these shares are synthetic outputs, not
vote-share estimates, and the ranges are narrower than the real uncertainty.

Nothing here queries a model: the bootstrap reuses the saved answers. Each
model/day has its own seed, so adding a new day never changes earlier forecasts.

Outputs (data/forecast/): state_forecasts.parquet (one row per day x model x
state), seat_draws.parquet (one row per day x model x draw) and
seat_summary.parquet (one row per day x model).

Usage (repository root): uv run python src/forecast.py
The website build (src/prepare_website.py) calls add_bootstrap_forecasts()
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

DEFAULT_OUTPUT_DIR = ROOT / "data/forecast"
DRAWS = 10_000
BASE_SEED = 2026
INTERVAL = (0.05, 0.95)  # 90 per cent intervals
MAJORITY = 51


def seed_for(*parts):
    """A stable seed per model/day so earlier forecasts never change."""
    return np.random.default_rng([BASE_SEED, *(zlib.crc32(str(p).encode()) for p in parts)])


def bootstrap_states(rng, personas, draws=DRAWS):
    """Draws of each state's Democratic two-party share from resampled personas.

    personas maps state -> (P(Democrat) array, P(Republican) array), one entry per
    sampled persona row. Returns (sorted states, draws x states array).
    """
    states = sorted(personas)
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
    return states, shares


def seat_totals(shares, fixed_seats):
    """Seats per draw: fixed seats plus states with a Democratic share above 50%."""
    dem_wins = (shares > 0.5).sum(axis=1)
    return {"democratic_seats": fixed_seats["democrat"] + dem_wins,
            "republican_seats": fixed_seats["republican"] + shares.shape[1] - dem_wins,
            "independent_seats": np.full(shares.shape[0], fixed_seats["independent"])}


def summarise(states, shares, seats, personas):
    """State shares, intervals and win chances; seat median, interval and control."""
    low, high = INTERVAL
    state_rows = {}
    for s, state in enumerate(states):
        dem, rep = (np.asarray(a, dtype=float) for a in personas[state])
        state_rows[state] = {"share": float(dem.sum() / (dem + rep).sum()),
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


def forecast_entry(entry, key, day, fixed_seats, draws=DRAWS):
    """Bootstrap forecast for one website snapshot entry (one model, one day)."""
    personas = {state: ([p["p_democrat"] for p in values["points"]],
                        [p["p_republican"] for p in values["points"]])
                for state, values in entry["states"].items()}
    states, shares = bootstrap_states(seed_for(day, key), personas, draws)
    seats = seat_totals(shares, fixed_seats)
    state_rows, seat_summary = summarise(states, shares, seats, personas)
    return {"states": state_rows, "seats": seat_summary}, seats


def add_bootstrap_forecasts(history, draws=DRAWS, keep_draws=False):
    """Attach entry['forecast'] to every complete synthetic model/day in history.

    External benchmarks and incomplete days are skipped (their 'forecast' is
    None). With keep_draws, seat draws are kept under
    history['seat_draws'][(day, key)] for saving as Parquet.
    """
    fixed = history["baseline"]["fixed_seats"]
    history["forecast_settings"] = {"draws": draws, "interval": list(INTERVAL)}
    if keep_draws:
        history["seat_draws"] = {}
    for day, snapshot in history["snapshots"].items():
        for key, entry in snapshot["models"].items():
            entry["forecast"] = None
            if entry.get("kind") == "external_forecast" or not entry.get("complete"):
                continue
            entry["forecast"], seats = forecast_entry(entry, key, day, fixed, draws)
            if keep_draws:
                history["seat_draws"][(day, key)] = seats
    return history


def forecast_tables(history):
    """Parquet-ready tables from a history with bootstrap forecasts."""
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
                              **{k: v for k, v in seats.items() if k != "histogram"}})
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
    history = add_bootstrap_forecasts(load_history(ROOT), args.draws, keep_draws=True)
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
