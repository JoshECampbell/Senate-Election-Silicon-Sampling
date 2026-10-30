"""Check paired four-option bootstraps, their SE, and the classic seat rule."""
import sys
from pathlib import Path
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'src'))
from bootstrap_responses import bootstrap_means, summarise_means, seat_draws_from_means
from site_figures import bootstrap_seat_dot_figure


class ResponseBootstrapTests(unittest.TestCase):
    def test_complete_vectors_are_sampled_together(self):
        values = np.array([[.8, .1, .05, .05]]*50 + [[.1, .2, .3, .4]]*50)
        means = bootstrap_means(values, np.random.default_rng(3), 10_000)
        np.testing.assert_allclose(means.sum(axis=1), 1)
        # Every category is the same linear function of the number of A draws.
        count = (means[:, 0]-.1)/.7
        np.testing.assert_allclose(means[:, 3], .4-.35*count)
        summary = summarise_means(values, means)
        se = summary['p_democrat']['sem']
        self.assertAlmostEqual(summary['p_democrat']['mean'], .45)
        self.assertAlmostEqual(se, means[:, 0].std(ddof=1))
        # The known SE of a bootstrap mean of these 100 values is 0.035.
        self.assertAlmostEqual(se, .035, delta=.001)
        self.assertGreater(se, .02)  # catches erroneously dividing by sqrt(10000)

    def test_repeated_draws_retain_their_multiplicity(self):
        values = np.array([[1., 0, 0, 0]]*75 + [[0, 1., 0, 0]]*25)
        means = bootstrap_means(values, np.random.default_rng(7), 10_000)
        self.assertAlmostEqual(means[:, 0].mean(), .75, delta=.002)

    def test_identical_draws_have_no_resampling_uncertainty(self):
        values = np.tile([.2, .3, .1, .4], (100, 1))
        means = bootstrap_means(values, np.random.default_rng(1), 20)
        np.testing.assert_allclose(means, np.tile(values[0], (20, 1)))
        self.assertLess(summarise_means(values, means)['p_democrat']['sem'], 1e-12)

    def test_bad_shapes_and_numbers_are_rejected(self):
        for values in (np.ones((99, 4))/4, np.ones((100, 2))/2,
                       np.ones((100, 4)), np.full((100, 4), np.nan)):
            with self.assertRaises(ValueError):
                bootstrap_means(values, np.random.default_rng(1), 10)

    def test_third_party_and_ties_follow_original_seat_rule(self):
        states = {'A': np.array([[.1, .2, .6, .1], [.4, .4, .1, .1]]),
                  'B': np.array([[.3, .1, .1, .5], [.1, .2, .1, .6]])}
        seats = seat_draws_from_means(states, {'democrat': 32, 'republican': 31, 'independent': 2})
        self.assertEqual(seats['independent'].tolist(), [3, 2])
        self.assertEqual(seats['unallocated'].tolist(), [0, 1])
        self.assertEqual(seats['democrat'].tolist(), [33, 32])
        self.assertEqual(seats['republican'].tolist(), [31, 32])
        np.testing.assert_equal(sum(seats.values()), [67, 67])

    def test_dot_plot_summarises_all_replicates_in_fifty_dots(self):
        content = bootstrap_seat_dot_figure('Example', {'democrat': [40]*10_000, 'republican': [58]*10_000},
                                          {'democrat': 40, 'republican': 58},
                                          {'democrat': {'sem': .8}, 'republican': {'sem': .9}})
        self.assertEqual(content.count('data-resamples="10000"'), 2)
        self.assertEqual(content.count('data-display-count="25"'), 2)
        self.assertEqual(content.count('class="bootstrap-summary-dot"'), 50)
        self.assertIn('40 ± 0.80 seats', content)
        self.assertIn('58 ± 0.90 seats', content)
        self.assertNotIn('full Senate bootstrap', content)


if __name__ == '__main__':
    unittest.main()
