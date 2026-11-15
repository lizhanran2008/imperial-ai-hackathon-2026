"""Once a pot is re-raised we raise again only with TT+ and AK (Sunday bucket rounds 1-5)."""

import unittest

from src import preflop
from src.common import DEFAULT_PROFILE

import test_jam_callers as jc

VALUE = (["As", "Ac"], ["Kh", "Kc"], ["Qh", "Qc"], ["Jh", "Jc"], ["Th", "Tc"], ["Ad", "Kd"], ["Ad", "Kc"])
OTHER = (["9h", "9c"], ["8h", "8c"], ["Ad", "Qd"], ["Ad", "Qc"], ["Ad", "Jc"], ["Ad", "5d"],
         ["Ah", "2h"], ["Qh", "Jd"], ["Jh", "Td"], ["Kd", "Qh"])


def _profiles(model=None):
    return model.profiles() if model else {i: dict(DEFAULT_PROFILE) for i in range(jc.N)}


class RaiseOverAReraiseIsForValue(unittest.TestCase):
    def test_weaker_hands_call_or_fold(self):
        for model in (None, jc._model(["fold"] * 8), jc._model(["call"] * 8)):
            for hole in OTHER:
                d = preflop.decide(jc._facing_3bet(hole), _profiles(model))
                self.assertIn(d.get("action"), ("call", "fold"), hole)

    def test_value_hands_still_raise(self):
        for hole in VALUE:
            d = preflop.decide(jc._facing_3bet(hole), _profiles())
            self.assertEqual(d.get("action"), "raise", hole)

    def test_first_reraise_is_untouched(self):
        saved = preflop._RR_VALUE_ONLY
        for hole in OTHER + VALUE:
            state = jc._facing_3bet(hole)
            # Take the re-raise away: we are in the small blind facing a single open.
            state["history"] = [h for h in state["history"] if not (h["seat"] == 0 and h["action"] == "raise")][:3]
            state["history"][2] = {"seat": 3, "street": "preflop", "action": "raise", "amount": 65}
            state["seat"] = 0
            state["bets"] = [10, 20, 0, 65, 0, 0, 0]
            state["stacks"] = [1990, 1980, 2000, 1935, 2000, 2000, 2000]
            state["folded"] = [False, False, True, False, True, True, True]
            state["pot"], state["to_call"], state["min_raise_to"] = 95, 55, 110
            state["raises_this_street"] = 1
            try:
                preflop._RR_VALUE_ONLY = True
                on = preflop.decide(dict(state), _profiles())
                preflop._RR_VALUE_ONLY = False
                off = preflop.decide(dict(state), _profiles())
            finally:
                preflop._RR_VALUE_ONLY = saved
            self.assertEqual(on, off, hole)


if __name__ == "__main__":
    unittest.main()
