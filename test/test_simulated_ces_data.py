"""Tests run against the saved simulated cleaned-CES frame.

- Require the same 17 columns and storage types as the real cleaned CES file.
- Check allowed response codes, adult birth years, unique IDs and finite positive weights.
- Prove the shared checks reject an invalid response code and a changed storage type.

Usage: uv run python -m unittest discover -s test -p 'test_simulated_ces_data.py' -v
Generate the data first with: uv run python src/simulate_data.py
Relationships between variables are tested in test_simulated_pipeline.py.
"""

from pathlib import Path
import unittest

import polars as pl

from ces_checks import assert_ranges, assert_schema

ROOT = Path(__file__).resolve().parents[1]


class SimulatedCESDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = pl.read_parquet(ROOT / 'data/simulated/cleaned_CES_data.parquet')

    def test_columns_and_types_match_cleaned_ces(self):
        assert_schema(self, self.frame)

    def test_values_are_in_expected_ranges(self):
        assert_ranges(self, self.frame)

    def test_checks_reject_bad_codes_and_changed_types(self):
        # Mutate only in-memory copies, leaving the saved fixture untouched.
        with self.assertRaises(AssertionError):
            assert_ranges(self, self.frame.with_columns(pl.lit(12345).alias('race')))
        with self.assertRaises(AssertionError):
            assert_schema(self, self.frame.with_columns(pl.col('race').cast(pl.Float64)))


if __name__ == '__main__':
    unittest.main()
