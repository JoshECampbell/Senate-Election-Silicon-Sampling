"""Download official 2024 presidential results by state for the back-cast.

Source: MIT Election Data and Science Lab, "U.S. President 1976-2024", Harvard
Dataverse, doi:10.7910/DVN/42MVDX, V10.1, file 1976-2024-president.csv
(CC0 1.0, so the file can be kept in the repository).

Workflow: download the original CSV through the Dataverse API (it redirects to
a short-lived storage link) -> check its published MD5 -> save it unchanged
under data/election_results/ -> keep 2024, non-write-in rows for Harris and
Trump -> save one row per state with both candidates' votes, the state total
and Harris's share of the two-party vote.
Usage (repository root): uv run python src/election_results_pull.py
"""

import hashlib
from pathlib import Path

import polars as pl
import requests

FILE_ID = 13887042  # 1976-2024-president.csv
DATA_URL = f"https://dataverse.harvard.edu/api/access/datafile/{FILE_ID}"
EXPECTED_MD5 = "405af83db7625cb35d8c19a5ebe029ff"
OUTPUT_DIR = Path("data/election_results")
RAW_FILE = OUTPUT_DIR / "1976-2024-president.csv"
STATE_FILE = OUTPUT_DIR / "president_2024_by_state.parquet"
CANDIDATES = {"HARRIS, KAMALA D.": "harris_votes", "TRUMP, DONALD J.": "trump_votes"}


def pull_raw(url=DATA_URL, path=RAW_FILE):
    """Save the original file, refusing anything that is not the published version."""
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    digest = hashlib.md5(response.content).hexdigest()
    if digest != EXPECTED_MD5:
        raise ValueError(f"Downloaded file has MD5 {digest}, expected {EXPECTED_MD5}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)


def state_results(raw):
    """One row per state (and DC) with Harris and Trump votes and totals.

    Candidates are matched by name because party labels vary by state, and
    write-in rows can carry similar names. Summing allows a candidate to appear
    on more than one party line.
    """
    rows = raw.filter(pl.col("year") == 2024, pl.col("writein").cast(pl.String).str.to_lowercase() == "false",
                      pl.col("candidate").is_in(list(CANDIDATES)))
    wide = (rows.with_columns(pl.col("candidate").replace_strict(CANDIDATES))
            .pivot(on="candidate", index=["state", "state_po", "state_fips"],
                   values="candidatevotes", aggregate_function="sum"))
    totals = rows.group_by("state_po").agg(pl.col("totalvotes").max())
    return (wide.join(totals, on="state_po")
            .with_columns(pl.col("state").str.to_titlecase(),
                          (pl.col("harris_votes") / (pl.col("harris_votes") + pl.col("trump_votes")))
                          .alias("harris_two_party"))
            .with_columns(pl.col("state").str.replace("Of", "of"))
            .select("state", "state_po", "state_fips", "harris_votes", "trump_votes", "totalvotes",
                    "harris_two_party")
            .sort("state"))


if __name__ == "__main__":
    pull_raw()
    raw = pl.read_csv(RAW_FILE, infer_schema_length=None, encoding="utf8")
    results = state_results(raw)
    if results.height != 51:
        raise ValueError(f"Expected 50 states and DC, found {results.height}.")
    results.write_parquet(STATE_FILE)
    print(f"Saved {RAW_FILE} and {STATE_FILE} ({results.height} states and DC).")
