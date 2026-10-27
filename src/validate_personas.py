"""Compare sampled personas with weighted CES respondents within each state.

Workflow: load reference data, sampled personas and settings -> check respondent
identity/state -> compare weighted CES shares with unweighted draw frequencies
-> write tables, plots and input/count metadata.
Usage: uv run python src/validate_personas.py --run-name sample_100
"""

from argparse import ArgumentParser
from pathlib import Path
import math
import re
import textwrap

import numpy as np
import polars as pl
import yaml


DEFAULT_DATA_PATH = Path("data/cleaned/cleaned_CES_data.parquet")
DEFAULT_CONFIG = Path("config/persona_validation.yaml")
DEFAULT_LABELS = Path("config/ces_codes/ces25_value_labels.yaml")
DEFAULT_OUTPUT_DIR = Path("data/persona_validation")
NO_RESPONSE = "No response"
INVALID_AGE = "Outside age range / invalid birth year"


def args_parser():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", required=True, help="Persona set name and output name")
    parser.add_argument("--personas", type=Path, help="Input folder (default: data/personas/<run-name>)")
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--features", nargs="+", help="age or categorical CES variable names")
    parser.add_argument("--states", nargs="+", help="State names; quote names that contain spaces")
    parser.add_argument("--age-reference-year", type=int)
    parser.add_argument("--age-bin-edges", nargs="+", type=int)
    return parser.parse_args()



def load_settings(args):
    with open(args.config, encoding="utf-8") as file:
        settings = yaml.safe_load(file)
    with open(args.labels, encoding="utf-8") as file:
        labels = yaml.safe_load(file)["variables"]

    # Settings define the comparison; labels translate raw CES response codes.

    # Keep the default settings unless the caller supplies an override.
    for key in ("features", "age_reference_year", "age_bin_edges"):
        value = getattr(args, key)
        if value is not None:
            settings[key] = value
    features = settings["features"]
    if not features or len(features) != len(set(features)):
        raise ValueError("Select at least one feature, with no duplicate names.")
    for feature in features:
        if feature != "age" and "codes" not in labels.get(feature, {}):
            raise ValueError(f"Unsupported feature: {feature}. Use age or a coded CES variable.")
    edges = settings["age_bin_edges"]
    if len(edges) < 2 or any(type(x) is not int for x in edges):
        raise ValueError("Age bin edges must contain at least two integers.")
    if edges[0] < 0 or any(a >= b for a, b in zip(edges, edges[1:])):
        raise ValueError("Age bin edges must be nonnegative and strictly increasing.")
    if type(settings["age_reference_year"]) is not int:
        raise ValueError("The age reference year must be an integer.")
    return settings, labels


def category_spec(feature, settings, labels):
    """Return the category order and a function that labels one raw value."""
    if feature == "age":
        edges = settings["age_bin_edges"]
        categories = [f"{low}-{high - 1}" for low, high in zip(edges, edges[1:])]

        def label_value(value):
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return NO_RESPONSE
            try:
                year = float(value)
            except (TypeError, ValueError):
                return INVALID_AGE
            if not math.isfinite(year) or not year.is_integer():
                return INVALID_AGE
            age = settings["age_reference_year"] - int(year)
            for low, high, category in zip(edges, edges[1:], categories):
                if low <= age < high:
                    return category
            return INVALID_AGE

        return categories + [NO_RESPONSE, INVALID_AGE], label_value

    codes = labels[feature]["codes"]
    no_response = set(settings["no_response_labels"])

    # Keep configured categories even when absent, then append unexpected values
    # so both distributions use exactly the same denominator and category set.
    categories = list(dict.fromkeys(str(label) for label in codes.values() if label not in no_response))

    def label_value(value):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return NO_RESPONSE
        # Do not round an unexpected fractional code into a valid category.
        label = codes.get(value)
        if label is None:
            return f"Unknown code: {value}"
        return NO_RESPONSE if label in no_response else str(label)

    return categories + [NO_RESPONSE], label_value


def compare_feature(reference, personas, feature, settings, labels):
    """Use survey weights for the reference and equal weights for persona draws."""
    column = "birthyr" if feature == "age" else feature
    categories, label_value = category_spec(feature, settings, labels)
    reference_labels = [label_value(x) for x in reference[column].to_list()]
    persona_labels = [label_value(x) for x in personas[column].to_list()]
    unknown = sorted((set(reference_labels) | set(persona_labels)) - set(categories))
    categories += unknown

    # CES survey weights describe the reference distribution. Each persona row
    # is one draw, so repeated rows deliberately count more than once.
    weights = reference["commonweight"].cast(pl.Float64).to_numpy()
    if not np.all(np.isfinite(weights)) or np.any(weights < 0) or weights.sum() <= 0:
        raise ValueError("Reference weights must be finite, nonnegative, and have a positive sum.")
    if personas.height == 0 or reference.height == 0:
        raise ValueError("Both the reference and the persona set must contain respondents.")

    rows = []
    for order, category in enumerate(categories):
        reference_mask = np.array([x == category for x in reference_labels])
        persona_count = persona_labels.count(category)
        weight_sum = float(weights[reference_mask].sum())
        reference_share = weight_sum / float(weights.sum())
        persona_share = persona_count / personas.height
        rows.append({
            "feature": feature, "source_column": column,
            "category_order": order, "category": category,
            "reference_count": int(reference_mask.sum()),
            "reference_weight_sum": weight_sum,
            "reference_total_count": reference.height,
            "reference_total_weight": float(weights.sum()),
            "persona_count": persona_count, "persona_total_count": personas.height,
            "reference_share": reference_share, "persona_share": persona_share,
            "difference_pp": 100 * (persona_share - reference_share),
        })
    return rows


def check_personas(reference, personas, columns, state_code):
    """Keep repeated draws, but reject records that do not match their source."""
    required = set(columns) | {"caseid", "inputstate"}
    if required - set(personas.columns):
        raise ValueError(f"Missing persona columns: {sorted(required - set(personas.columns))}")
    if personas.height == 0:
        raise ValueError("The persona file is empty.")
    if any(code != state_code for code in personas["inputstate"].to_list()):
        raise ValueError("The persona file contains an incorrect or missing state code.")

    # Index source rows once. Repeated persona draws are valid; changed values are not.
    source = {row["caseid"]: row for row in reference.select(sorted(required)).to_dicts()}
    for row in personas.select(sorted(required)).to_dicts():
        original = source.get(row["caseid"])
        if original is None:
            raise ValueError("A persona identifier is absent from this state's reference data.")
        for column in columns:
            actual, expected = row[column], original[column]
            both_nan = (isinstance(actual, float) and isinstance(expected, float)
                        and math.isnan(actual) and math.isnan(expected))
            if actual != expected and not both_nan:
                raise ValueError(f"A persona value does not match the reference column: {column}")


def plot_state(distributions, state, run_name, settings, labels, output_path):
    """Save a panel of paired horizontal bars, as in the supplied reference figure."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    features = settings["features"]
    # Increase panel height for long category lists, such as income or state.
    largest = max(distributions.filter(pl.col("feature") == f).height for f in features)
    columns = min(3, len(features))
    rows = math.ceil(len(features) / columns)
    fig, axes = plt.subplots(rows, columns, figsize=(7 * columns, max(4.5, largest * .34) * rows),
                             squeeze=False, layout="constrained")
    for axis, feature in zip(axes.flat, features):
        data = distributions.filter(pl.col("feature") == feature).sort("category_order")
        positions = np.arange(data.height)
        axis.barh(positions - .19, data["persona_share"], height=.36, color="#222222", label="Sampled personas")
        axis.barh(positions + .19, data["reference_share"], height=.36, color="#AAAAAA", label="State CES respondents (weighted)")
        axis.set_yticks(positions, [textwrap.fill(x, 29) for x in data["category"]])
        axis.invert_yaxis()
        axis.set_xlim(0, 1)
        axis.set_xticks([0, .25, .5, .75, 1])
        axis.xaxis.set_major_formatter(PercentFormatter(1))
        axis.set_axisbelow(True)
        axis.grid(axis="x", alpha=.25)
        title = (f"Age in {settings['age_reference_year']} (approximate)" if feature == "age"
                 else labels[feature]["description"])
        axis.set_title(textwrap.fill(title, 48), fontsize=11)
        axis.tick_params(labelsize=9)
        for spine in axis.spines.values():
            spine.set_visible(False)
    for axis in list(axes.flat)[len(features):]:
        axis.set_visible(False)
    first = distributions.row(0, named=True)
    fig.suptitle(f"{state} | Persona run: {run_name}\n"
                 f"{first['persona_total_count']:,} draws; {first['reference_total_count']:,} reference respondents",
                 fontsize=15)
    handles, legend_labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="outside lower center", ncols=2, frameon=False)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def validate_personas():
    args = args_parser()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.run_name):
        raise ValueError("Use a run name with letters, numbers, dots, underscores, or hyphens.")
    settings, labels = load_settings(args)
    persona_dir = args.personas or Path("data/personas") / args.run_name
    if not persona_dir.is_dir():
        raise ValueError(f"Persona folder does not exist: {persona_dir}")
    states = {name: code for code, name in labels["inputstate"]["codes"].items()
              if code not in labels["inputstate"].get("missing", [])}
    # Read .parquet files and accept legacy extensionless Parquet files too.
    files = {}
    for path in sorted(persona_dir.iterdir()):
        if not path.is_file() or path.name.startswith(".") or path.suffix not in ("", ".parquet"):
            continue
        state = path.stem
        if state not in states or state in files:
            raise ValueError(f"Unrecognized or duplicate state file: {path}")
        files[state] = path
    selected = args.states or list(files)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Select at least one state, with no duplicate names.")
    if set(selected) - set(files):
        raise ValueError(f"Persona files not found for: {sorted(set(selected) - set(files))}")

    # Read the selected features and the fields required for input checks.
    columns = list(dict.fromkeys("birthyr" if f == "age" else f for f in settings["features"]))
    required = sorted(set(columns) | {"caseid", "inputstate", "commonweight"})
    df = pl.scan_parquet(args.data_path).select(required).collect()
    if df["caseid"].null_count() or df["caseid"].n_unique() != df.height:
        raise ValueError("Reference identifiers must be unique and non-missing.")

    distribution_rows, summary_rows, state_metadata = [], [], {}
    # Calculate all results before writing files, so input errors stop the run early.
    for state in selected:
        reference = df.filter(pl.col("inputstate") == states[state])
        personas = pl.read_parquet(files[state])
        check_personas(reference, personas, columns, states[state])
        for feature in settings["features"]:
            rows = compare_feature(reference, personas, feature, settings, labels)
            for row in rows:
                row.update(run_name=args.run_name, state=state, state_code=states[state])
            distribution_rows.extend(rows)
            summary_rows.append({
                "run_name": args.run_name, "state": state, "feature": feature,
                "total_variation_distance": .5 * sum(abs(r["persona_share"] - r["reference_share"]) for r in rows),
                "max_absolute_difference_pp": max(abs(r["difference_pp"]) for r in rows),
            })
        state_metadata[state] = {
            "persona_file": str(files[state]),
            "persona_draws": personas.height,
            "reference_population": reference.height,
        }
        print(f"Compared {state}: {personas.height} draws / {reference.height} reference respondents")

    output_dir = args.output_dir / args.run_name
    plot_dir = output_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    distributions = pl.DataFrame(distribution_rows)
    distribution_path = output_dir / f"{args.run_name}_distributions.parquet"
    summary_path = output_dir / f"{args.run_name}_summary.parquet"
    distributions.write_parquet(distribution_path)
    pl.DataFrame(summary_rows).write_parquet(summary_path)
    for state in selected:
        path = plot_dir / f"{state.replace(' ', '_')}.png"
        plot_state(distributions.filter(pl.col("state") == state), state, args.run_name, settings, labels, path)

    metadata = {
        "reference": str(args.data_path),
        "personas": {
            "directory": str(persona_dir),
            "total_draws": sum(state["persona_draws"] for state in state_metadata.values()),
            "states": state_metadata,
        },
    }
    metadata_path = output_dir / f"{args.run_name}_validation.yaml"
    with open(metadata_path, "w", encoding="utf-8") as file:
        yaml.safe_dump(metadata, file, sort_keys=False, allow_unicode=True)
    print(f"Validation results saved to: {output_dir}")


if __name__ == "__main__":
    validate_personas()
