"""Check matched categories, signed pp differences, and eligible denominators."""
from pathlib import Path
import sys
import unittest
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.validate_electoral_responses import SPECS, score_categories


class MatchedEvaluationTests(unittest.TestCase):
    def test_house_keeps_unsure_and_uses_same_eligible_draws(self):
        frame = pl.DataFrame({'model_key': ['m']*5, 'state': ['A']*5,
                              'probability_valid': [True, True, True, True, False],
                              'CC25_363': [2, 2, 4, 98, 3],
                              'p_would_not_vote': [.1]*5, 'p_democrat': [.2]*5,
                              'p_republican': [.3]*5, 'p_not_sure': [.4]*5})
        rows, coverage = score_categories(frame, SPECS['house'],
                                         ['Would not vote', 'Democrat', 'Republican', 'Not sure'])
        dem = rows.filter(option='Democrat').row(0, named=True)
        unsure = rows.filter(option='Not sure').row(0, named=True)
        self.assertEqual(dem['eligible_draws'], 3)
        self.assertAlmostEqual(dem['actual'], 2/3)
        self.assertAlmostEqual(dem['difference_pp'], 100*(.2-2/3))
        self.assertAlmostEqual(unsure['actual'], 1/3)
        self.assertEqual(coverage['missing_survey_draws'].item(), 1)
        self.assertEqual(rows.height, 4)

    def test_president_groups_other_candidates_and_preserves_nonvoting(self):
        frame = pl.DataFrame({'model_key': ['m']*4, 'state': ['A']*4,
                              'probability_valid': [True]*4, 'presvote24post': [3, 8, 9, 99],
                              'p_democrat': [.1]*4, 'p_republican': [.2]*4,
                              'p_third_party': [.4]*4, 'p_would_not_vote': [.3]*4})
        rows, _ = score_categories(frame, SPECS['president'],
                                   ['Democrat', 'Republican', 'Third party', 'Would not vote'])
        self.assertAlmostEqual(rows.filter(option='Third party')['actual'].item(), 2/3)
        self.assertAlmostEqual(rows.filter(option='Would not vote')['actual'].item(), 1/3)

    def test_no_eligible_answers_are_unavailable_not_zero(self):
        frame = pl.DataFrame({'model_key': ['m'], 'state': ['A'], 'CC25_363': [98],
                              'probability_valid': [True], 'p_not_sure': [.25], 'p_democrat': [.25],
                              'p_republican': [.25], 'p_would_not_vote': [.25]})
        rows, _ = score_categories(frame, SPECS['house'],
                                   ['Would not vote', 'Democrat', 'Republican', 'Not sure'])
        self.assertEqual(rows['predicted'].null_count(), 4)
        self.assertEqual(rows['difference_pp'].null_count(), 4)


if __name__ == '__main__':
    unittest.main()
