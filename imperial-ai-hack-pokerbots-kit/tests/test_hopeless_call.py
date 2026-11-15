"""No flop/turn call with nothing against a bet of two thirds of the pot or more (Sunday rounds 1-11)."""

import unittest

from src import agent


def _state(hole, board, to_call, pot, raises=1, street="flop"):
    hist = [{"seat": 0, "street": "preflop", "action": "raise", "amount": 50 * (i + 1)} for i in range(raises)]
    return {"street": street, "hole_cards": hole, "board": board, "to_call": to_call, "pot": pot,
            "history": hist, "legal_actions": ["fold", "call", "raise"]}


class HopelessCall(unittest.TestCase):
    def test_nothing_against_a_big_bet_is_hopeless(self):
        self.assertTrue(agent._hopeless_call(_state(["Ac", "Jd"], ["Ts", "4c", "7d"], 112, 272)))
        self.assertTrue(agent._hopeless_call(_state(["Kd", "9h"], ["Th", "2h", "7s"], 160, 320)))

    def test_a_pair_or_a_strong_draw_is_not(self):
        self.assertFalse(agent._hopeless_call(_state(["Ac", "Td"], ["Ts", "4c", "7d"], 112, 272)))
        self.assertFalse(agent._hopeless_call(_state(["Ah", "Jh"], ["Th", "4h", "7d"], 112, 272)))
        self.assertFalse(agent._hopeless_call(_state(["9c", "8d"], ["Ts", "4c", "7d"], 112, 272)))

    def test_small_bets_rivers_and_reraised_pots_are_left_alone(self):
        self.assertFalse(agent._hopeless_call(_state(["Ac", "Jd"], ["Ts", "4c", "7d"], 50, 272)))
        self.assertFalse(agent._hopeless_call(
            _state(["Ac", "Jd"], ["Ts", "4c", "7d", "2s", "3h"], 112, 272, street="river")))
        self.assertFalse(agent._hopeless_call(_state(["Ac", "Jd"], ["Ts", "4c", "7d"], 112, 272, raises=2)))


if __name__ == "__main__":
    unittest.main()
