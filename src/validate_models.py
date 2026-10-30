"""Check saved model answers against the real CES answers held out of the prompts.

Each persona row keeps its respondent's own 2026 House intention (CC25_363) and
2024 presidential vote (presvote24post). Neither is sent to a model, so they are
a fair benchmark for the four probabilities the model returned.

Workflow
--------
1. Load every dated run (data/llm_responses/<mon>-<day>-*/results.parquet) or
   the runs named with --runs. Only rows with probability_valid are scored;
   coverage records how many were dropped.
2. Map each benchmark to the four options:
     2026 intention: Democratic -> Democrat, Republican -> Republican,
                     do not intend to vote -> Would not vote; "Not sure" and
                     missing answers are not scored.
     2024 vote:      Harris -> Democrat, Trump -> Republican, other candidates
                     -> Third party, did not vote -> Would not vote.
3. Individual agreement, by run x model x benchmark: accuracy of the most likely
   option, the accuracy of always guessing the most common answer, log loss,
   Brier score, and two-party accuracy among Democratic/Republican answers.
4. Aggregate agreement: mean probability of each option against the share of
   personas who gave that answer (the comparison in Murray and Alexander's
   Figure 2), and a calibration table of P(Democrat | Democrat or Republican).
5. States: the forecast's two-party share, sum P(D) / sum(P(D) + P(R)), against
   (a) the same 100 personas' 2026 intention and (b) all weighted CES
   respondents in the state. Then each model's spread across run days.
6. 2024 back-cast (if data/llm_responses/backcast-2024 exists): the same models
   asked how each persona voted in 2024. Individual answers are scored against
   presvote24post, and each state's two-party share is compared with the
   official result (data/election_results/, from election_results_pull.py).
   The summary gives each model's average error, largest error, correlation
   with the result and how many state winners it gets right.

Persona rows are weighted draws, so every row counts once; a respondent drawn
three times counts three times. Do not apply commonweight again.

Outputs (data/model_validation/): individual.parquet, option_shares.parquet,
calibration.parquet, states.parquet, run_stability.parquet, and for the
back-cast backcast_individual.parquet, backcast_states.parquet and
backcast_summary.parquet, plus validation.yaml

Usage (repository root): uv run python src/validate_models.py
Optional: --runs oct-28-no-luna oct-29-no-luna --backcast-run backcast-2024
          --output-dir data/model_validation
"""

from argparse import ArgumentParser
from pathlib import Path
import re
import sys

import numpy as np
import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from create_personas import SENATE_STATES_2026

RUNS_DIR = ROOT / "data/llm_responses"
DEFAULT_CES = ROOT / "data/cleaned/cleaned_CES_data.parquet"
DEFAULT_RESULTS_2024 = ROOT / "data/election_results/president_2024_by_state.parquet"
DEFAULT_BACKCAST = "backcast-2024"
DEFAULT_OUTPUT_DIR = ROOT / "data/model_validation"
DATED_RUN = re.compile(r"^[a-z]{3}-\d{1,2}-")

OPTIONS = ["Democrat", "Republican", "Third party", "Would not vote"]
P_COLUMNS = ["p_democrat", "p_republican", "p_third_party", "p_would_not_vote"]
BENCHMARKS = {
    "2026 House intention": ("CC25_363", {1: "Would not vote", 2: "Democrat", 3: "Republican"}),
    "2024 presidential vote": ("presvote24post", {1: "Democrat", 2: "Republican", 3: "Third party",
                                                  4: "Third party", 5: "Third party", 6: "Third party",
                                                  8: "Third party", 9: "Would not vote"}),
}
CALIBRATION_BINS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
GROUP = ["run", "model_key"]
EPSILON = 1e-6  # floor for log loss so a probability of exactly 0 is finite


def load_runs(names=None, runs_dir=RUNS_DIR):
    """Stack the chosen runs' results with a run column."""
    if names is None:
        names = sorted(p.name for p in runs_dir.iterdir()
                       if DATED_RUN.match(p.name) and (p / "results.parquet").exists())
    if not names:
        raise FileNotFoundError(f"No dated runs with results.parquet in {runs_dir}.")
    columns = ["model_key", "state", "persona_row", "caseid", "CC25_363", "presvote24post",
               "probability_valid", *P_COLUMNS]
    return pl.concat(pl.read_parquet(runs_dir / name / "results.parquet", columns=columns)
                     .with_columns(pl.lit(name).alias("run")) for name in names)


def with_target(results, benchmark):
    """Add the benchmark's option label; rows it cannot score get null."""
    column, mapping = BENCHMARKS[benchmark]
    return results.with_columns(
        pl.col(column).replace_strict(mapping, default=None, return_dtype=pl.String).alias("target"))


def scored_rows(results, benchmark):
    """Valid answers with a scorable benchmark answer."""
    return with_target(results, benchmark).filter(pl.col("probability_valid"),
                                                  pl.col("target").is_not_null())


def score_individuals(results):
    """Agreement between each persona's probabilities and their own answer."""
    tables = []
    for benchmark in BENCHMARKS:
        rows = scored_rows(results, benchmark)
        probs = rows.select(P_COLUMNS).to_numpy()
        target = rows["target"].to_numpy()
        onehot = np.column_stack([target == option for option in OPTIONS]).astype(float)
        rows = rows.with_columns(
            pl.Series("correct", np.array(OPTIONS)[probs.argmax(axis=1)] == target),
            pl.Series("log_loss", -np.log(np.clip((probs * onehot).sum(axis=1), EPSILON, 1))),
            pl.Series("brier", ((probs - onehot) ** 2).sum(axis=1)),
            (pl.col("p_democrat") / (pl.col("p_democrat") + pl.col("p_republican"))).alias("two_party"),
        )
        modal = (rows.group_by(*GROUP, "target").len()
                 .group_by(GROUP).agg((pl.col("len").max() / pl.col("len").sum()).alias("baseline_accuracy")))
        two_party = (rows.filter(pl.col("target").is_in(["Democrat", "Republican"]))
                     .group_by(GROUP).agg(
                         ((pl.col("two_party") > 0.5) == (pl.col("target") == "Democrat"))
                         .mean().alias("two_party_accuracy")))
        totals = results.group_by(GROUP).agg(pl.len().alias("rows"),
                                             pl.col("probability_valid").mean().alias("coverage"))
        scores = rows.group_by(GROUP).agg(pl.len().alias("scored"), pl.col("correct").mean().alias("accuracy"),
                                          pl.col("log_loss").mean(), pl.col("brier").mean())
        # Start from every run x model so a model that never answered still
        # appears, with scored = 0 and null scores, instead of disappearing.
        tables.append(
            totals.join(scores, on=GROUP, how="left").join(modal, on=GROUP, how="left")
            .join(two_party, on=GROUP, how="left")
            .with_columns(pl.col("scored").fill_null(0), pl.lit(benchmark).alias("benchmark")))
    return pl.concat(tables).select("run", "model_key", "benchmark", "rows", "coverage", "scored",
                                    "accuracy", "baseline_accuracy", "two_party_accuracy",
                                    "log_loss", "brier").sort("benchmark", "run", "model_key")


def option_shares(results):
    """Mean probability of each option against the share who gave that answer."""
    tables = []
    for benchmark in BENCHMARKS:
        rows = scored_rows(results, benchmark)
        for option, column in zip(OPTIONS, P_COLUMNS):
            tables.append(rows.group_by(GROUP).agg(
                pl.col(column).mean().alias("predicted"),
                (pl.col("target") == option).mean().alias("actual"),
            ).with_columns(pl.lit(benchmark).alias("benchmark"), pl.lit(option).alias("option")))
    return (pl.concat(tables).with_columns((pl.col("predicted") - pl.col("actual")).alias("error"))
            .select("run", "model_key", "benchmark", "option", "predicted", "actual", "error")
            .sort("benchmark", "run", "model_key", "option"))


def calibration(results, benchmark="2026 House intention"):
    """Bins of P(Democrat | two-party) against the Democratic share in each bin."""
    rows = (scored_rows(results, benchmark)
            .filter(pl.col("target").is_in(["Democrat", "Republican"]))
            .with_columns((pl.col("p_democrat") / (pl.col("p_democrat") + pl.col("p_republican")))
                          .alias("predicted")))
    labels = np.array([f"{low:.1f}-{high:.1f}"
                       for low, high in zip([0, *CALIBRATION_BINS], [*CALIBRATION_BINS, 1])])
    bins = labels[np.digitize(rows["predicted"].to_numpy(), CALIBRATION_BINS)]
    return (rows.with_columns(pl.Series("bin", bins))
            .group_by("model_key", "bin")
            .agg(pl.len().alias("n"), pl.col("predicted").mean(),
                 (pl.col("target") == "Democrat").mean().alias("actual"))
            .with_columns(pl.lit(benchmark).alias("benchmark"))
            .sort("model_key", "bin"))


def ces_state_intention(ces):
    """Weighted Democratic share of Democratic + Republican House intentions."""
    return (ces.filter(pl.col("CC25_363").is_in([2, 3]),
                       pl.col("inputstate").is_in(list(SENATE_STATES_2026)))
            .group_by("inputstate")
            .agg((((pl.col("CC25_363") == 2) * pl.col("commonweight")).sum()
                  / pl.col("commonweight").sum()).alias("ces_two_party"))
            .with_columns(pl.col("inputstate").replace_strict(SENATE_STATES_2026).alias("state"))
            .select("state", "ces_two_party"))


def state_comparison(results, ces=None):
    """Each state's forecast-style two-party share against the CES benchmarks."""
    valid = results.filter(pl.col("probability_valid"))
    predicted = valid.group_by(*GROUP, "state").agg(
        (pl.col("p_democrat").sum() / (pl.col("p_democrat") + pl.col("p_republican")).sum())
        .alias("predicted_two_party"))
    personas = (results.filter(pl.col("CC25_363").is_in([2, 3]))
                .group_by(*GROUP, "state")
                .agg((pl.col("CC25_363") == 2).mean().alias("persona_two_party")))
    table = predicted.join(personas, on=[*GROUP, "state"], how="left")
    table = table.with_columns((pl.col("predicted_two_party") - pl.col("persona_two_party"))
                               .alias("error_vs_personas"))
    if ces is not None:
        table = (table.join(ces_state_intention(ces), on="state", how="left")
                 .with_columns((pl.col("predicted_two_party") - pl.col("ces_two_party"))
                               .alias("error_vs_ces")))
    return table.sort("run", "model_key", "state")


def run_stability(states):
    """How much each model's state share moves between run days."""
    return (states.group_by("model_key", "state")
            .agg(pl.len().alias("runs"), pl.col("predicted_two_party").mean().alias("mean"),
                 pl.col("predicted_two_party").std().alias("sd"),
                 pl.col("predicted_two_party").min().alias("min"),
                 pl.col("predicted_two_party").max().alias("max"))
            .sort("model_key", "state"))


def backcast_states(backcast, actual):
    """Each state's back-cast two-party share against the official 2024 result."""
    predicted = (backcast.filter(pl.col("probability_valid"))
                 .group_by("model_key", "state")
                 .agg((pl.col("p_democrat").sum() / (pl.col("p_democrat") + pl.col("p_republican")).sum())
                      .alias("predicted_two_party")))
    table = predicted.join(actual.select("state", pl.col("harris_two_party").alias("actual_two_party")),
                           on="state", how="left")
    missing = table.filter(pl.col("actual_two_party").is_null())["state"].unique().to_list()
    if missing:
        raise ValueError(f"No official 2024 result for: {missing}")
    return (table.with_columns((pl.col("predicted_two_party") - pl.col("actual_two_party")).alias("error"))
            .sort("model_key", "state"))


def backcast_summary(states):
    """Per model: how well the back-cast ranks states and how far off it is."""
    return (states.group_by("model_key")
            .agg(pl.len().alias("states"),
                 pl.col("error").mean().alias("mean_error"),
                 pl.col("error").abs().mean().alias("mean_abs_error"),
                 pl.col("error").abs().max().alias("max_abs_error"),
                 (pl.col("error") ** 2).mean().sqrt().alias("rmse"),
                 pl.corr("predicted_two_party", "actual_two_party").alias("correlation"),
                 ((pl.col("predicted_two_party") > 0.5) == (pl.col("actual_two_party") > 0.5))
                 .mean().alias("winner_agreement"))
            .sort("model_key"))


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", help="Run folder names (default: every dated run)")
    parser.add_argument("--backcast-run", default=DEFAULT_BACKCAST,
                        help="2024 back-cast run folder (skipped if it does not exist)")
    parser.add_argument("--results-2024", type=Path, default=DEFAULT_RESULTS_2024)
    parser.add_argument("--ces", type=Path, default=DEFAULT_CES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    results = load_runs(args.runs)
    ces = pl.read_parquet(args.ces) if args.ces.exists() else None
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    individual = score_individuals(results)
    states = state_comparison(results, ces)
    individual.write_parquet(out / "individual.parquet")
    option_shares(results).write_parquet(out / "option_shares.parquet")
    calibration(results).write_parquet(out / "calibration.parquet")
    states.write_parquet(out / "states.parquet")
    run_stability(states).write_parquet(out / "run_stability.parquet")

    summary = None
    if (RUNS_DIR / args.backcast_run / "results.parquet").exists():
        backcast = load_runs([args.backcast_run])
        (score_individuals(backcast).filter(pl.col("benchmark") == "2024 presidential vote")
         .write_parquet(out / "backcast_individual.parquet"))
        back_states = backcast_states(backcast, pl.read_parquet(args.results_2024))
        back_states.write_parquet(out / "backcast_states.parquet")
        summary = backcast_summary(back_states)
        summary.write_parquet(out / "backcast_summary.parquet")

    with open(out / "validation.yaml", "w", encoding="utf-8") as file:
        yaml.safe_dump({"runs": sorted(results["run"].unique().to_list()),
                        "rows": results.height,
                        "ces_benchmark": str(args.ces.relative_to(ROOT)) if ces is not None else None,
                        "backcast_run": args.backcast_run if summary is not None else None,
                        "results_2024": str(args.results_2024.relative_to(ROOT)) if summary is not None
                        else None},
                       file)

    with pl.Config(tbl_rows=-1, tbl_cols=-1, tbl_width_chars=160, float_precision=3):
        print(individual.group_by("model_key", "benchmark")
              .agg(pl.col("accuracy", "baseline_accuracy", "two_party_accuracy", "log_loss").mean())
              .sort("benchmark", "model_key"))
        error = "error_vs_ces" if ces is not None else "error_vs_personas"
        print(states.group_by("model_key").agg(
            pl.col(error).mean().alias("mean_error"), pl.col(error).abs().mean().alias("mean_abs_error"))
            .sort("model_key"))
        if summary is not None:
            print(summary)
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
