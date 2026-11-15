"""A light re-raise is skipped when three or more seats are still to act behind us (Sunday rounds 1-10)."""

import unittest

from src import preflop
from src.opponents import OpponentModel

ME, OPENER, N = 3, 2, 8
LIGHT = (["Ks", "5s"], ["Jh", "8h"], ["Qd", "9d"], ["7c", "6c"], ["Ah", "4h"], ["Td", "7s"], ["9s", "3h"])


def _model():
    """The opener has folded to every re-raise it has faced."""
    m = OpponentModel()
    m.start({"num_players": N, "seat": ME})
    for i in range(12):
        m.observe({
            "type": "hand_end", "hand_number": i + 1, "board": [], "shown": {},
            "history": [
                {"seat": 0, "street": "preflop", "action": "small_blind", "amount": 10},
                {"seat": 1, "street": "preflop", "action": "big_blind", "amount": 20},
                {"seat": OPENER, "street": "preflop", "action": "raise", "amount": 60},
                {"seat": ME, "street": "preflop", "action": "raise", "amount": 192},
                {"seat": OPENER, "street": "preflop", "action": "fold", "amount": 0},
            ],
        })
    return m


def _facing_open(hole):
    """Seat 2 opened to 60 first in; we are next with seats 4-7 and both blinds still to act."""
    stacks = [2000] * N
    bets = [0] * N
    stacks[0], bets[0] = 1990, 10
    stacks[1], bets[1] = 1980, 20
    stacks[OPENER], bets[OPENER] = 1940, 60
    hist = [
        {"seat": 0, "street": "preflop", "action": "small_blind", "amount": 10},
        {"seat": 1, "street": "preflop", "action": "big_blind", "amount": 20},
        {"seat": OPENER, "street": "preflop", "action": "raise", "amount": 60},
    ]
    return {
        "street": "preflop", "seat": ME, "button": 7, "hole_cards": hole, "board": [],
        "stacks": stacks, "bets": bets, "folded": [False] * N, "pot": 90, "to_call": 60,
        "min_raise_to": 100, "max_raise_to": 2000, "legal_actions": ["fold", "call", "raise"],
        "small_blind": 10, "big_blind": 20, "blind_level": 0, "hand_number": 50,
        "betting": "no_limit", "raise_cap": None, "raises_this_street": 1, "history": hist,
    }


def _light_raise(decision):
    return decision.get("action") == "raise" and decision.get("amount", 0) < 1900


class LightReraiseNeedsFewSeatsBehind(unittest.TestCase):
    def _decide(self, hole):
        return preflop.decide(_facing_open(hole), _model().profiles())

    def test_no_light_reraise_with_six_seats_behind(self):
        for hole in LIGHT:
            self.assertFalse(_light_raise(self._decide(hole)), hole)

    def test_the_rule_is_what_stops_them(self):
        saved = preflop._3B_MAX_BEHIND
        preflop._3B_MAX_BEHIND = 99
        try:
            raised = [hole for hole in LIGHT if _light_raise(self._decide(hole))]
        finally:
            preflop._3B_MAX_BEHIND = saved
        self.assertTrue(raised)

    def test_big_hands_still_raise(self):
        for hole in (["As", "Ac"], ["Kh", "Kc"], ["Ad", "Kd"]):
            self.assertEqual(self._decide(hole).get("action"), "raise", hole)


if __name__ == "__main__":
    unittest.main()
