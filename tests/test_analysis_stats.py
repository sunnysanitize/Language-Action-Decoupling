# The statistics behind every headline number in RESULTS.md and FINDINGS.md.
#
# This file exists because these modules had no tests at all. numpy, scipy and
# scikit-learn are optional -- an episode runs and the rest of the suite passes
# without them -- so the analysis layer was never exercised by
# `python -m unittest discover`, and a p-value of 1.033 reached a committed
# results document without anything failing.

import unittest

try:
    import numpy as np

    from experiments.analysis import two_sided_p
except ImportError:  # pragma: no cover - matches the optional-dependency note
    np = None


@unittest.skipIf(np is None, "numpy is not installed")
class TwoSidedPTests(unittest.TestCase):
    # The bug this replaced: 2 * min((v <= 0).mean(), (v >= 0).mean()) counts a
    # resample of exactly zero on both sides, so ties inflate the result past
    # the top of the probability scale.
    def test_ties_do_not_push_the_p_value_above_one(self):
        values = np.array([0.0] * 1700 + [0.01] * 150 + [-0.01] * 150)

        self.assertLessEqual(two_sided_p(values), 1.0)

    def test_all_ties_give_no_evidence_against_the_null(self):
        self.assertEqual(two_sided_p(np.zeros(2000)), 1.0)

    def test_a_one_sided_effect_is_significant(self):
        values = np.array([0.02] * 1980 + [-0.01] * 20)

        self.assertAlmostEqual(two_sided_p(values), 0.02, places=6)

    def test_an_evenly_split_sample_is_not_significant(self):
        values = np.array([0.01] * 1000 + [-0.01] * 1000)

        self.assertEqual(two_sided_p(values), 1.0)

    def test_the_result_is_always_a_probability(self):
        generator = np.random.default_rng(0)
        for trial in range(200):
            # Heavy ties on purpose: that is the regime the old form broke in.
            values = generator.integers(-1, 2, size=50).astype(float)
            with self.subTest(trial=trial):
                probability = two_sided_p(values)
                self.assertGreaterEqual(probability, 0.0)
                self.assertLessEqual(probability, 1.0)

    def test_direction_does_not_change_the_p_value(self):
        values = np.array([0.02] * 1980 + [-0.01] * 20)

        self.assertEqual(two_sided_p(values), two_sided_p(-values))

    def test_an_empty_sample_is_not_a_p_value(self):
        self.assertTrue(np.isnan(two_sided_p(np.array([]))))


if __name__ == "__main__":
    unittest.main()


try:
    from experiments.detector import Evaluation
    from experiments.report import _adds_signal
except ImportError:  # pragma: no cover - optional dependency
    Evaluation = None


def _evaluation(positives: int) -> "Evaluation":
    return Evaluation(
        model="1_situation",
        rows=1200,
        positives=positives,
        base_rate=0.02,
        auprc=0.1,
        auprc_lift=5.0,
        auroc=0.7,
        brier=0.1,
    )


@unittest.skipIf(Evaluation is None, "scikit-learn is not installed")
class AddsSignalTests(unittest.TestCase):
    # runs/capital-main reported p = 0.011 on a delta of 0.000 over 4
    # positives, and the table printed that as "yes". The gain was real in
    # direction and far below the precision the table prints, so the verdict
    # column contradicted the number beside it.
    def test_a_significant_but_sizeless_gain_is_not_a_gain(self):
        verdict = _adds_signal(
            {"1_situation": _evaluation(400)},
            {"p_no_gain": 0.011, "delta_auprc": 0.0004},
        )

        self.assertEqual(verdict, "negligible")

    def test_too_few_positives_is_reported_rather_than_asserted(self):
        verdict = _adds_signal(
            {"1_situation": _evaluation(4)},
            {"p_no_gain": 0.011, "delta_auprc": 0.4},
        )

        self.assertEqual(verdict, "too few (4)")

    def test_a_real_gain_still_reads_as_yes(self):
        verdict = _adds_signal(
            {"1_situation": _evaluation(41)},
            {"p_no_gain": 0.001, "delta_auprc": 0.052},
        )

        self.assertEqual(verdict, "**yes**")

    def test_an_insignificant_gain_reads_as_no(self):
        verdict = _adds_signal(
            {"1_situation": _evaluation(63)},
            {"p_no_gain": 0.317, "delta_auprc": 0.011},
        )

        self.assertEqual(verdict, "no")
