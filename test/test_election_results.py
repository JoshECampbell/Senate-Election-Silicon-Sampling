"""Tests of the 2024 presidential results used for the back-cast.

- state_results keeps only 2024, non-write-in Harris and Trump rows, sums a
  candidate's party lines, and computes Harris's two-party share.
- The saved file has 50 states and DC, every Senate state, shares in (0, 1),
  candidate votes no larger than the total, and the published Texas count.

Usage: uv run python -m unittest discover -s test -p 'test_election_results.py' -v
Download the data first with: uv run python src/election_results_pull.py
"""

from pathlib import Path
import sys
import unittest

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from create_personas import SENATE_STATES_2026
from election_results_pull import STATE_FILE, state_results


def raw_row(candidate, votes, year=2024, writein="False", total=1000, state="ALPHA", po="AL"):
    return {"year": year, "state": state, "state_po": po, "state_fips": 1, "candidate": candidate,
            "writein": writein, "candidatevotes": votes, "totalvotes": total}


class StateResultsTests(unittest.TestCase):
    def test_filters_and_shares(self):
        raw = pl.DataFrame([
            raw_row("HARRIS, KAMALA D.", 300),
            raw_row("HARRIS, KAMALA D.", 100),             # second party line, same candidate
            raw_row("TRUMP, DONALD J.", 500),
            raw_row("HARRIS, KAMALA D.", 50, writein="True"),
            raw_row("STEIN, JILL", 40),
            raw_row("BIDEN, JOSEPH R. JR", 900, year=2020),
        ])
        result = state_results(raw).row(0, named=True)
        self.assertEqual(result["state"], "Alpha")
        self.assertEqual(result["harris_votes"], 400)
        self.assertEqual(result["trump_votes"], 500)
        self.assertEqual(result["totalvotes"], 1000)
        self.assertAlmostEqual(result["harris_two_party"], 400 / 900)


@unittest.skipUnless((ROOT / STATE_FILE).exists(), "Run src/election_results_pull.py first.")
class SavedResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = pl.read_parquet(ROOT / STATE_FILE)

    def test_every_state_and_senate_race(self):
        self.assertEqual(self.results.height, 51)
        self.assertEqual(self.results["state"].n_unique(), 51)
        self.assertFalse(set(SENATE_STATES_2026.values()) - set(self.results["state"]))

    def test_values_are_consistent(self):
        self.assertEqual(self.results.null_count().sum_horizontal().item(), 0)
        self.assertTrue(self.results["harris_two_party"].is_between(0, 1, closed="none").all())
        both = self.results["harris_votes"] + self.results["trump_votes"]
        self.assertTrue((both <= self.results["totalvotes"]).all())

    def test_published_texas_count(self):
        texas = self.results.filter(state_po="TX").row(0, named=True)
        self.assertEqual((texas["harris_votes"], texas["trump_votes"], texas["totalvotes"]),
                         (4835250, 6393597, 11388674))


if __name__ == "__main__":
    unittest.main()
