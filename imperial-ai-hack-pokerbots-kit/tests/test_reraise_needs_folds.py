"""Light re-raises stop against a seat that does not fold to ours; offsuit hands fold to a re-raise."""

import unittest

from src import preflop
from src.opponents import OpponentModel
from tests.test_jam_callers import _facing_3bet

ME, OPENER, N = 2, 5, 7


def _hand(answer, number):
    """The opener raises, we re-raise from the big blind seat order, the opener answers."""
    return {
        "type": "hand_end", "hand_number": number, "board": [], "shown": {},
        "history": [
            {"seat": 0, "street": "preflop", "action": "small_blind", "amount": 10},
            {"seat": 1, "street": "preflop", "action": "big_blind", "amount": 20},
            {"seat": OPENER, "street": "preflop", "action": "raise", "amount": 50},
            {"seat": ME, "street": "preflop", "action": "raise", "amount": 160},
            {"seat": OPENER, "street": "preflop", "action": answer,
             "amount": 110 if answer == "call" else 0},
        ],
    }


def _model(answers):
    m = OpponentModel()
    m.start({"num_players": N, "seat": ME})
    for i, a in enumerate(answers):
        m.observe(_hand(a, i + 1))
    return m


def _facing_open(hole):
    """Seat 5 opened to 50, everyone else folded, we are on the button (seat 6 is the button)."""
    stacks = [2000] * N
    bets = [0] * N
    stacks[0], bets[0] = 1990, 10
    stacks[1], bets[1] = 1980, 20
    stacks[OPENER], bets[OPENER] = 1950, 50
    me = 6
    folded = [s in (2, 3, 4) for s in range(N)]
    hist = [
        {"seat": 0, "street": "preflop", "action": "small_blind", "amount": 10},
        {"seat": 1, "street": "preflop", "action": "big_blind", "amount": 20},
    ] + [{"seat": s, "street": "preflop", "action": "fold", "amount": 0} for s in (2, 3, 4)] + [
        {"seat": OPENER, "street": "preflop", "action": "raise", "amount": 50},
    ]
    return {
        "street": "preflop", "seat": me, "button": 6, "hole_cards": hole, "board": [],
        "stacks": stacks, "bets": bets, "folded": folded, "pot": 80, "to_call": 50,
        "min_raise_to": 80, "max_raise_to": 2000, "legal_actions": ["fold", "call", "raise"],
        "small_blind": 10, "big_blind": 20, "blind_level": 0, "hand_number": 50,
        "betting": "no_limit", "raise_cap": None, "raises_this_street": 1, "history": hist,
    }


class HeroFoldStat(unittest.TestCase):
    def test_reported_only_after_three_of_our_reraises(self):
        self.assertNotIn("fold_to_hero_3bet", _model(["call"] * 2).profiles()[OPENER])
        self.assertIn("fold_to_hero_3bet", _model(["call"] * 3).profiles()[OPENER])

    def test_reads_low_for_a_caller_and_high_for_a_folder(self):
        self.assertLess(_model(["call"] * 6).profiles()[OPENER]["fold_to_hero_3bet"], 0.4)
        self.assertGreater(_model(["fold"] * 6).profiles()[OPENER]["fold_to_hero_3bet"], 0.8)


class LightReraiseNeedsFolds(unittest.TestCase):
    def _decide(self, hole, profile_edit):
        profiles = _model(["fold"] * 6).profiles()
        profile_edit(profiles[OPENER])
        return preflop.decide(_facing_open(hole), profiles)

    def test_light_hand_stops_reraising_a_seat_that_does_not_fold_to_us(self):
        folds = self._decide(["Ks", "5s"], lambda p: p.update(fold_to_hero_3bet=0.9, fold_to_3bet=0.9))
        stays = self._decide(["Ks", "5s"], lambda p: p.update(fold_to_hero_3bet=0.3, fold_to_3bet=0.9))
        self.assertEqual(folds.get("action"), "raise")
        self.assertNotEqual(stays.get("action"), "raise")

    def test_value_hand_still_reraises(self):
        d = self._decide(["Ks", "Kd"], lambda p: p.update(fold_to_hero_3bet=0.1))
        self.assertEqual(d.get("action"), "raise")


class OffsuitFoldsToAReraise(unittest.TestCase):
    def test_offsuit_hands_fold_and_suited_or_paired_hands_are_unchanged(self):
        profiles = {}
        for hole in (["Ah", "Jd"], ["Kh", "Qd"], ["Ah", "Td"]):
            self.assertEqual(preflop.decide(_facing_3bet(hole), profiles).get("action"), "fold", hole)
        preflop._RR_OFFSUIT_FOLD = False
        try:
            before = [preflop.decide(_facing_3bet(h), profiles) for h in (["Ah", "Jh"], ["9h", "9d"], ["Ah", "Kd"])]
        finally:
            preflop._RR_OFFSUIT_FOLD = True
        after = [preflop.decide(_facing_3bet(h), profiles) for h in (["Ah", "Jh"], ["9h", "9d"], ["Ah", "Kd"])]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
