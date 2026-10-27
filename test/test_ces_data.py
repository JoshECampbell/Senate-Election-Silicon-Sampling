"""Tests run against the saved real CES files (no downloads or data changes).

- Require data/raw/raw_CES_2025_Common.tab and exactly 17,000 respondent rows.
- Require all 17 selected codebook variables in the raw file.
- Require the named cleaned Parquet file, 17,000 rows and the expected columns/types.
- Check IDs, weights, birth-year ranges and response codes using the shared CES checks.
- Compare all cleaned rows with the 17 selected raw columns, including nulls and row order.

Usage: uv run python -m unittest discover -s test -p 'test_ces_data.py' -v
"""

from pathlib import Path
import sys
import unittest

import polars as pl
from polars.testing import assert_frame_equal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from data_cleaning import CES_COLUMNS
from ces_checks import LABELS, assert_ranges, assert_schema


class CESDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Missing files fail explicitly: these tests inspect saved local data.
        cls.raw = pl.read_csv(ROOT / 'data/raw/raw_CES_2025_Common.tab', separator='\t')
        cls.cleaned = pl.read_parquet(ROOT / 'data/cleaned/cleaned_CES_data.parquet')

    def test_raw_name_count_and_required_codebook_variables(self):
        self.assertEqual(self.raw.height, 17_000)
        self.assertEqual(len(LABELS), 17)
        self.assertEqual(set(LABELS), set(CES_COLUMNS))
        self.assertTrue(set(LABELS).issubset(self.raw.columns))

    def test_cleaned_count_columns_and_types(self):
        self.assertEqual(self.cleaned.height, 17_000)
        assert_schema(self, self.cleaned)

    def test_cleaned_values_and_ranges(self):
        assert_ranges(self, self.cleaned)

    def test_cleaning_preserves_selected_raw_values_and_row_order(self):
        assert_frame_equal(self.cleaned, self.raw.select(list(CES_COLUMNS)))


if __name__ == '__main__':
    unittest.main()
