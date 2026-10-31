"""Check that the new website reports matched CES comparisons and bootstrap SEs."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from site_evaluation import matched_validation_section, bootstrap_headline, matched_evaluation_costs, average_state_comparisons


class SiteEvaluationTests(unittest.TestCase):
    def test_state_comparison_uses_signed_pp_and_keeps_unsure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root/'data/model_validation'
            out.mkdir(parents=True)
            (out/'matched_manifest.json').write_text(json.dumps({'house': {'status': 'available'},
                                                                'president': {'status': 'pending'}}))
            pl.DataFrame([{'evaluation': '2026 House intention', 'model_key': 'm', 'state': state,
                           'option': 'Not sure', 'eligible_draws': 90, 'predicted': .2, 'actual': .1,
                           'difference_pp': 10.} for state in ('Alabama', 'Alaska')]).write_parquet(out/'matched_state_categories.parquet')
            content = matched_validation_section(root, {'m': {'label': 'Example'}})
        self.assertEqual(content.count('data-evaluation-state='), 2)
        self.assertIn('Not sure', content)
        self.assertIn('matched-model-dot', content)
        self.assertIn('ces-reference-dot', content)
        self.assertIn('<details>', content)
        self.assertLess(content.index('Average across states'), content.index('id="evaluation-state"'))
        self.assertNotIn('Difference = model mean minus recorded CES share', content)
        self.assertIn('+10.0 pp', content)
        self.assertIn('not yet been collected', content)
        self.assertNotIn('official results', content)

    def test_headline_keeps_classic_counts_and_labels_bootstrap_se(self):
        parts = {p: {'sem': .8, 'mean': 40.} for p in ('democrat', 'republican', 'independent', 'unallocated')}
        entry = {'senate': {'totals': {'democrat': 40, 'republican': 58, 'independent': 2, 'unallocated': 0}},
                 'bootstrap_senate': {'resamples': 10000, 'parties': parts}}
        content = bootstrap_headline('m', {'label': 'Example'}, '2026-10-30', entry)
        self.assertIn('Bootstrap Results', content)
        self.assertNotIn('bootstrap-seat-estimates', content)
        self.assertNotIn('figure-caption', content)
        self.assertNotIn('two-party', content)

    def test_average_gives_each_state_equal_weight(self):
        frame = pl.DataFrame({'evaluation': ['e']*3, 'model_key': ['m']*3,
                              'option': ['Democrat']*3, 'state': ['A', 'B', 'C'],
                              'predicted': [.8, .2, None], 'actual': [.6, .2, None],
                              'eligible_draws': [100, 10, 0]})
        result = average_state_comparisons(frame).row(0, named=True)
        self.assertAlmostEqual(result['predicted'], .5)
        self.assertAlmostEqual(result['actual'], .4)
        self.assertAlmostEqual(result['difference_pp'], 10)
        self.assertEqual(result['state_count'], 2)
        self.assertEqual(result['eligible_draws'], 110)

    def test_evaluation_costs_include_both_token_counts_without_inventing_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root/'data/model_validation'
            out.mkdir(parents=True)
            (out/'matched_manifest.json').write_text(json.dumps({'house': {'status': 'available', 'run': 'r'},
                                                                'president': {'status': 'available', 'run': 'old'}}))
            for name in ('r', 'old'):
                folder = root/'data/llm_responses'/name
                folder.mkdir(parents=True)
                pl.DataFrame({'model_key': ['m'], 'state': ['A'], 'caseid': [1],
                              'cost_usd': [.01], 'input_tokens': [100]}).write_parquet(folder/'results.parquet')
            (out/'matched_usage.json').write_text(json.dumps({'house': {'m': {
                'attempts': 1, 'partial': False, 'known_cost': .01, 'unknown_costs': 0,
                'input_tokens': 1234, 'unknown_input_tokens': 0,
                'output_tokens': 5, 'unknown_output_tokens': 0}}}))
            content = matched_evaluation_costs(root, {'m': {'label': 'Example'}})
        self.assertIn('Input tokens', content)
        self.assertIn('Output tokens', content)
        self.assertIn('1,234', content)
        self.assertIn('<td>5</td>', content)
        self.assertIn('Unknown', content)


if __name__ == '__main__':
    unittest.main()
