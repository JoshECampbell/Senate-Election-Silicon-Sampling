"""Generate a small, artificial cleaned-CES dataset for offline tests.

Workflow: read the project's 17-variable codebook -> generate seeded values and
some legitimate missing responses -> apply the existing cleaned storage types
-> save a separate Parquet file. No real respondents are read or copied.
This is a software fixture, not a representative sample or a research input.

Usage (repository root): uv run python src/simulate_cleaned_ces.py
Optional: --rows 128 --seed 42 --output data/simulated/cleaned_CES_data.parquet
"""

from argparse import ArgumentParser
from pathlib import Path
import random

import polars as pl
import yaml

from data_cleaning import CES_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'data/simulated/cleaned_CES_data.parquet'


def simulate_cleaned_ces(rows=128, seed=42):
    """Use codebook categories and the CES 2025 adult age range (18–120)."""
    if rows < 1:
        raise ValueError('Choose at least one simulated row.')
    rng = random.Random(seed)
    labels = yaml.safe_load((ROOT / 'config/ces_codes/ces25_value_labels.yaml').read_text())['variables']
    data = {}
    for column in CES_SCHEMA:
        if column == 'caseid':
            data[column] = [float(i + 1) for i in range(rows)]
        elif column == 'birthyr':
            data[column] = [rng.randint(1905, 2007) for _ in range(rows)]
        elif column == 'commonweight':
            data[column] = [rng.uniform(.05, 3) for _ in range(rows)]
        else:
            codes = list(labels[column]['codes'])
            # Every row needs a real state for downstream state-based processing.
            if column == 'inputstate':
                codes = [code for code in codes if code not in labels[column]['missing']]
            data[column] = [rng.choice(codes) for _ in range(rows)]
    # These fields contain genuine nulls in the real cleaned export. Preserve
    # nullable integer storage rather than treating nulls as bad response codes.
    for column in ('religpew', 'marstat', 'sexuality', 'faminc_new', 'ideo5',
                   'CC25_363', 'presvote24post'):
        for i in range(0, rows, 17):
            data[column][i] = None
    return pl.DataFrame(data, schema=CES_SCHEMA)


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=int, default=128)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    frame = simulate_cleaned_ces(args.rows, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(args.output)
    print(f'Saved {frame.height} artificial cleaned-CES rows to {args.output}')
