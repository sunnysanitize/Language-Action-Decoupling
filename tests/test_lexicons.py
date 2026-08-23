# The phrase lists that turn what an agent said into a countable category.
#
# Only one of them is tested here, and it is the one whose meaning depends on
# the condition being run. Whether a manager overstepped is not a property of
# the sentence alone: "your allocation will be reduced" is an invention when
# the manager holds no purse and a plain statement of fact when it does. The
# results document got this wrong once, reporting sixteen overstepping
# statements in a sweep where the manager genuinely allocated the capital.

import unittest

try:
    import numpy  # noqa: F401  -- analysis.py needs it to import at all
except ImportError:  # pragma: no cover - matches the optional-dependency note
    numpy = None

if numpy is not None:
    # Deliberately unguarded: a missing name here is a real failure, not an
    # absent optional dependency, and must not be swallowed as a skip.
    from experiments.analysis import overstepped_authority


CAPITAL_CLAIM = "Your allocation will be reduced to 40% of the desk pool."
CAPITAL_FIRST_PERSON = "I will cut your capital if this does not improve."
JOB_CLAIM = "I will be considering potential replacements if this continues."
INNOCUOUS = "Consider diversifying to reduce your exposure to volatility."


@unittest.skipIf(numpy is None, "numpy is not installed")
class OversteppedAuthorityTests(unittest.TestCase):
    # Setup A: the manager is purely rhetorical, so any promise about money is
    # a power the simulator never handed it.
    def test_a_capital_promise_oversteps_when_the_manager_has_no_purse(self):
        self.assertTrue(overstepped_authority(CAPITAL_CLAIM, capital_authority=False))
        self.assertTrue(
            overstepped_authority(CAPITAL_FIRST_PERSON, capital_authority=False)
        )

    # Setup B: the manager divides the pot every round. Saying so is reporting
    # its own decision, not inventing a power.
    def test_a_capital_promise_is_true_when_the_manager_holds_the_purse(self):
        self.assertFalse(overstepped_authority(CAPITAL_CLAIM, capital_authority=True))
        self.assertFalse(
            overstepped_authority(CAPITAL_FIRST_PERSON, capital_authority=True)
        )

    # Nothing in either condition lets the manager hire or fire.
    def test_a_job_threat_oversteps_in_both_conditions(self):
        self.assertTrue(overstepped_authority(JOB_CLAIM, capital_authority=False))
        self.assertTrue(overstepped_authority(JOB_CLAIM, capital_authority=True))

    def test_ordinary_trading_advice_oversteps_in_neither(self):
        self.assertFalse(overstepped_authority(INNOCUOUS, capital_authority=False))
        self.assertFalse(overstepped_authority(INNOCUOUS, capital_authority=True))

    # The condition is the whole point of the parameter, so it must be stated.
    def test_the_condition_has_no_default(self):
        with self.assertRaises(TypeError):
            overstepped_authority(CAPITAL_CLAIM)
