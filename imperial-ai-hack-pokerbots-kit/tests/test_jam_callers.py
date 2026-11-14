"""A seat that keeps calling all-ins must stop being bluffed all-in (live round 12)."""

import unittest

from src import preflop
from src.common import DEFAULT_PROFILE
from src.opponents import OpponentModel

ME, VILLAIN, N = 2, 0, 7


def _hand(villain_answer, number):
    """We open, the villain re-raises, we move all-in, the villain answers."""
    return {
        "type": "hand_end", "hand_number": number, "board": [], "shown": {},
        "history": [
            {"seat": 0, "street": "preflop", "action": "small_blind", "amount": 10},
            {"seat": 1, "street": "preflop", "action": "big_blind", "amount": 20},
            {"seat": ME, "street": "preflop", "action": "raise", "amount": 65},
            {"seat": VILLAIN, "street": "preflop", "action": "raise", "amount": 234},
            {"seat": ME, "street": "preflop", "action": "raise", "amount": 2000},
            {"seat": VILLAIN, "street": "preflop", "action": villain_answer,
             "amount": 1766 if villain_answer == "call" else 0},
        ],
    }


def _model(answers):
    model = OpponentModel()
    model.start({"num_players": N, "seat": ME})
    for i, a in enumerate(answers):
        model.observe(_hand(a, i + 1))
    return model


def _facing_3bet(hole):
    """We opened to 65 first in, the small blind re-raised to 234, action is back on us."""
    stacks = [2000] * N
    bets = [0] * N
    stacks[0], bets[0] = 1766, 234
    stacks[1], bets[1] = 1980, 20
    stacks[ME], bets[ME] = 1935, 65
    folded = [s not in (0, ME) for s in range(N)]
    hist = [
        {"seat": 0, "street": "preflop", "action": "small_blind", "amount": 10},
        {"seat": 1, "street": "preflop", "action": "big_blind", "amount": 20},
        {"seat": ME, "street": "preflop", "action": "raise", "amount": 65},
    ] + [{"seat": s, "street": "preflop", "action": "fold", "amount": 0} for s in (3, 4, 5, 6)] + [
        {"seat": 0, "street": "preflop", "action": "raise", "amount": 234},
        {"seat": 1, "street": "preflop", "action": "fold", "amount": 0},
    ]
    return {
        "street": "preflop", "seat": ME, "button": 6, "hole_cards": hole, "board": [],
        "stacks": stacks, "bets": bets, "folded": folded, "pot": 319, "to_call": 169,
        "min_raise_to": 403, "max_raise_to": 2000, "legal_actions": ["fold", "call", "raise"],
        "small_blind": 10, "big_blind": 20, "blind_level": 0, "hand_number": 50,
        "betting": "no_limit", "raise_cap": None, "raises_this_street": 2, "history": hist,
    }


def _is_all_in(decision):
    return decision.get("action") == "raise" and decision.get("amount", 0) >= 1900


class CallJamStat(unittest.TestCase):
    def test_not_reported_until_seen_twice(self):
        self.assertNotIn("call_jam", _model(["call"]).profiles()[VILLAIN])
        self.assertNotIn("call_jam", dict(DEFAULT_PROFILE))

    def test_caller_reads_high_and_folder_reads_low(self):
        caller = _model(["call"] * 6).profiles()[VILLAIN]["call_jam"]
        folder = _model(["fold"] * 6).profiles()[VILLAIN]["call_jam"]
        self.assertGreater(caller, 0.7)
        self.assertLess(folder, 0.2)

    def test_only_seats_that_raised_are_counted(self):
        profiles = _model(["call"] * 6).profiles()
        self.assertNotIn("call_jam", profiles[1])   # big blind never raised
        self.assertNotIn("call_jam", profiles[ME])  # the all-in player itself


class BluffAllInsStopAgainstCallers(unittest.TestCase):
    BLUFFS = (["Qh", "6h"], ["Js", "Td"], ["Kd", "9h"], ["3c", "3d"])

    def _decide(self, hole, answers):
        return preflop.decide(_facing_3bet(hole), _model(answers).profiles())

    def test_bluff_hands_do_not_move_all_in_into_a_caller(self):
        for hole in self.BLUFFS:
            self.assertFalse(_is_all_in(self._decide(hole, ["call"] * 8)), hole)

    def test_big_hands_still_move_all_in_into_a_caller(self):
        for hole in (["As", "Ac"], ["Kh", "Kc"], ["Ad", "Kd"]):
            self.assertTrue(_is_all_in(self._decide(hole, ["call"] * 8)), hole)

    def test_a_seat_that_folds_is_treated_exactly_as_before(self):
        for hole in self.BLUFFS + (["As", "Ac"], ["Ad", "5d"]):
            state = _facing_3bet(hole)
            with_stat = preflop.decide(state, _model(["fold"] * 8).profiles())
            profiles = _model(["fold"] * 8).profiles()
            for p in profiles.values():
                p.pop("call_jam", None)
            self.assertEqual(with_stat, preflop.decide(_facing_3bet(hole), profiles), hole)


if __name__ == "__main__":
    unittest.main()
