"""V2: confidence bounds on measured rates (forge_eval.bounds).

The release targets in the plan rest on these numbers: 0 wrong in 300 shows
"under 1 in 100", 0 in 10,000 shows "under 1 in 3,000", 0 missed in 150
planted misreads shows a catch rate of at least 98%.
"""

from __future__ import annotations

import math
import unittest

from forge_eval import binomial_cdf, trials_needed, upper_bound


class TheBinomialCdf(unittest.TestCase):
    def test_small_cases_by_hand(self) -> None:
        self.assertAlmostEqual(binomial_cdf(0, 2, 0.5), 0.25)
        self.assertAlmostEqual(binomial_cdf(1, 2, 0.5), 0.75)
        self.assertAlmostEqual(binomial_cdf(1, 3, 0.2), 0.8**3 + 3 * 0.2 * 0.8**2)

    def test_edges(self) -> None:
        self.assertEqual(binomial_cdf(5, 5, 0.3), 1.0)
        self.assertEqual(binomial_cdf(-1, 5, 0.3), 0.0)
        self.assertEqual(binomial_cdf(2, 5, 0.0), 1.0)
        self.assertEqual(binomial_cdf(2, 5, 1.0), 0.0)

    def test_large_n_stays_finite(self) -> None:
        self.assertTrue(0.0 < binomial_cdf(30, 10_000, 0.003) < 1.0)


class UpperBounds(unittest.TestCase):
    def test_the_plan_s_release_numbers(self) -> None:
        self.assertLess(upper_bound(0, 300), 0.01)
        self.assertLess(upper_bound(0, 10_000), 1 / 3000)
        self.assertLessEqual(upper_bound(0, 150), 0.02)

    def test_no_failures_has_a_closed_form_near_three_over_n(self) -> None:
        for n in (30, 100, 1000):
            self.assertAlmostEqual(upper_bound(0, n), 1 - 0.05 ** (1 / n), places=12)
            self.assertAlmostEqual(upper_bound(0, n), 3 / n, delta=0.5 / n)

    def test_the_bound_solves_its_defining_equation(self) -> None:
        for k, n in ((1, 50), (3, 200), (10, 1000)):
            p = upper_bound(k, n)
            self.assertAlmostEqual(binomial_cdf(k, n, p), 0.05, places=9)

    def test_known_value(self) -> None:
        # One failure in 474 trials: the bound is just under 1 %.
        self.assertAlmostEqual(upper_bound(1, 474), 0.00997, places=5)

    def test_more_trials_tighter_more_failures_looser(self) -> None:
        self.assertLess(upper_bound(2, 400), upper_bound(2, 200))
        self.assertLess(upper_bound(1, 300), upper_bound(2, 300))

    def test_every_trial_failed(self) -> None:
        self.assertEqual(upper_bound(5, 5), 1.0)

    def test_bad_inputs(self) -> None:
        for args in ((0, 0), (-1, 10), (11, 10), (0, 10, 1.0), (0, 10, 0.0)):
            with self.assertRaises(ValueError, msg=args):
                upper_bound(*args)
        with self.assertRaises(TypeError):
            upper_bound(0.5, 10)  # type: ignore[arg-type]


class TrialsNeeded(unittest.TestCase):
    def test_the_plan_s_sample_sizes(self) -> None:
        self.assertEqual(trials_needed(0.01), 299)
        self.assertEqual(trials_needed(0.01, failures=1), 473)
        self.assertLessEqual(trials_needed(1 / 3000), 10_000)
        self.assertLessEqual(trials_needed(0.025), 120)

    def test_it_is_the_fewest(self) -> None:
        for rate, k in ((0.01, 0), (0.01, 2), (0.05, 1), (0.001, 0)):
            n = trials_needed(rate, k)
            self.assertLessEqual(upper_bound(k, n), rate)
            self.assertGreater(upper_bound(k, n - 1), rate)

    def test_bad_inputs(self) -> None:
        for rate in (0.0, 1.0, -0.1, math.nan):
            with self.assertRaises(ValueError):
                trials_needed(rate)
        with self.assertRaises(ValueError):
            trials_needed(0.1, failures=-1)


class OtherConfidences(unittest.TestCase):
    def test_low_confidence_bounds_are_right(self) -> None:
        # Found in review: the search once started at k/n and returned 0.1.
        p = upper_bound(1, 10, 0.2)
        self.assertAlmostEqual(binomial_cdf(1, 10, p), 0.8, places=9)
        self.assertLess(p, 0.1)

    def test_bad_confidence_for_trials_needed(self) -> None:
        for confidence in (0.0, 1.0, 1.5, math.nan):
            with self.assertRaises(ValueError):
                trials_needed(0.01, confidence=confidence)

    def test_bad_inputs_to_the_cdf(self) -> None:
        for n, p in ((10, math.nan), (-5, 0.5), (10, 1.5)):
            with self.assertRaises(ValueError):
                binomial_cdf(1, n, p)


if __name__ == "__main__":
    unittest.main()
