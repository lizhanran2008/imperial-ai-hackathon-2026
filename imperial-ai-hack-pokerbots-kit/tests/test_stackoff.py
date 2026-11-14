"""Big bets are only continued against with a hand near the top of the board (live rounds 28-38),
and an all-in over a re-raise without a pair or an ace needs a clear edge."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_jam_callers as jam_callers  # noqa: E402
from src import postflop_ranges_v4 as v4  # noqa: E402
from src import preflop  # noqa: E402
from src.common import DEFAULT_PROFILE  # noqa: E402

N, ME, VILLAIN = 8, 2, 5


def _facing(hole, board, pot_before, bet, street="flop"):
    """Heads-up after the flop: the villain bets `bet` into `pot_before`, action on us."""
    stacks = [2000] * N
    bets = [0] * N
    stacks[ME] = stacks[VILLAIN] = 2000 - pot_before // 2
    stacks[VILLAIN] -= bet
    bets[VILLAIN] = bet
    to_call = min(bet, stacks[ME])
    return {
        "street": street, "seat": ME, "button": 4, "hand_number": 7,
        "hole_cards": list(hole), "board": list(board),
        "pot": pot_before + bet, "to_call": to_call, "legal_actions": ["fold", "call"],
        "bets": bets, "stacks": stacks, "folded": [s not in (ME, VILLAIN) for s in range(N)],
        "min_raise_to": None, "max_raise_to": None, "raises_this_street": 1,
        "small_blind": 10, "big_blind": 20, "blind_level": 0, "betting": "no_limit", "raise_cap": None,
        "history": [
            {"seat": ME, "street": street, "action": "check", "amount": 0},
            {"seat": VILLAIN, "street": street, "action": "raise", "amount": bet},
        ],
    }


def _act(state):
    v4._tables.clear()
    return v4.decide(state, {s: dict(DEFAULT_PROFILE) for s in range(N)})["action"]


class StackoffFloor(unittest.TestCase):
    def test_ordinary_bets_have_no_floor(self):
        self.assertEqual(v4.stackoff_floor(100, 300), 0.0)      # half pot
        self.assertEqual(v4.stackoff_floor(300, 700), 0.0)      # three quarters of the pot
        self.assertEqual(v4.stackoff_floor(200, 300), 0.0)      # twice the pot, but small

    def test_pot_sized_bets_need_a_strong_hand(self):
        self.assertEqual(v4.stackoff_floor(400, 800), v4.PARAMS["big_bet_seff"])
        self.assertEqual(v4.stackoff_floor(1375, 2635), v4.PARAMS["big_bet_seff"])
        self.assertEqual(v4.stackoff_floor(400, 800, combo_draw=True), 0.0)

    def test_shoves_for_many_times_the_pot_need_a_very_strong_hand(self):
        self.assertEqual(v4.stackoff_floor(1935, 2085), v4.PARAMS["shove_seff"])
        self.assertEqual(v4.stackoff_floor(1935, 2085, combo_draw=True), v4.PARAMS["shove_seff"])


class HugeShoveIntoSmallPot(unittest.TestCase):
    BOARD = ["Kd", "9c", "5h"]

    def test_one_pair_and_ace_high_fold(self):
        for hole in (["5s", "2s"], ["Ah", "Td"], ["9d", "8d"], ["Kc", "7c"]):
            for _ in range(5):
                self.assertEqual(_act(_facing(hole, self.BOARD, 150, 1925)), "fold", hole)

    def test_sets_still_call(self):
        for hole in (["Ks", "Kh"], ["9s", "9h"], ["5s", "5d"]):
            self.assertEqual(_act(_facing(hole, self.BOARD, 150, 1925)), "call", hole)

    def test_guard_is_what_changes_the_answer(self):
        state = _facing(["Kc", "7c"], self.BOARD, 150, 1925)
        v4.PARAMS["use_stackoff_guard"] = False
        try:
            self.assertEqual(_act(state), "call")            # top pair used to call it off
        finally:
            v4.PARAMS["use_stackoff_guard"] = True
        self.assertEqual(_act(state), "fold")


class PotSizedRiverBet(unittest.TestCase):
    def test_second_pair_folds_and_the_nuts_calls(self):
        board = ["Ks", "7s", "2c", "9h", "8d"]
        self.assertEqual(_act(_facing(["Qs", "Qc"], board, 1260, 1370, "river")), "fold")
        self.assertEqual(_act(_facing(["Jd", "Tc"], board, 1260, 1370, "river")), "call")


def _jams(hole, on=True, folds=2):
    """We opened, the small blind re-raised; it has folded to `folds` earlier all-ins."""
    saved = preflop._JAM_NEEDS_EDGE
    preflop._JAM_NEEDS_EDGE = on
    try:
        d = preflop.decide(jam_callers._facing_3bet(hole), jam_callers._model(["fold"] * folds).profiles())
    finally:
        preflop._JAM_NEEDS_EDGE = saved
    return d.get("action") == "raise" and d.get("amount", 0) >= 1900


class AllInOverAReraise(unittest.TestCase):
    THIN = (["Js", "Td"], ["Kd", "Qh"], ["Qs", "Td"], ["Qh", "6h"])

    def test_no_pair_no_ace_does_not_move_in_on_a_thin_edge(self):
        for hole in self.THIN:
            self.assertTrue(_jams(hole, on=False), hole)     # the estimate alone says move in
            self.assertFalse(_jams(hole), hole)

    def test_a_clear_edge_still_moves_in(self):
        self.assertTrue(_jams(["Js", "Td"], folds=8))

    def test_pairs_and_aces_are_untouched(self):
        for hole in (["As", "Ac"], ["Kh", "Kc"], ["Ad", "Kd"], ["8s", "8h"], ["Ad", "5d"], ["Ah", "Jc"]):
            for folds in (2, 8):
                self.assertEqual(_jams(hole, folds=folds), _jams(hole, on=False, folds=folds), hole)
        self.assertTrue(_jams(["Ad", "5d"]))


def _jam_allowed(hole, to_call, width, edge=400.0, level=2):
    """PreflopBrain._jam_ok for an all-in over a re-raise costing `to_call` more, against a seat
    whose re-raising range is read as `width` of all hands."""
    brain = preflop._BRAIN
    brain.bb = 20
    return brain._jam_ok(preflop.cls_index(hole[0], hole[1]), level, edge, to_call, width)


class AllInOverABigReraise(unittest.TestCase):
    WEAK = (["Ah", "Td"], ["Ah", "Jh"], ["Ad", "5s"], ["7d", "7s"], ["Jd", "8d"])
    BIG = (["As", "Ac"], ["Kh", "Kc"], ["Ad", "Kd"], ["Ad", "Kc"], ["Th", "Tc"])

    def test_weak_hands_do_not_move_in_on_a_tight_reraiser(self):
        for hole in self.WEAK:
            self.assertFalse(_jam_allowed(hole, 240, 0.12), hole)

    def test_weak_hands_still_move_in_on_a_seat_that_reraises_often(self):
        # Live round 42: a limp-re-raiser to 576 that folded to most all-ins.
        for hole in self.WEAK:
            self.assertTrue(_jam_allowed(hole, 416, 0.30), hole)

    def test_big_hands_are_untouched(self):
        for hole in self.BIG:
            self.assertTrue(_jam_allowed(hole, 240, 0.05), hole)

    def test_an_ordinary_reraise_is_untouched(self):
        for hole in (["Ah", "Td"], ["Ad", "5d"], ["7d", "7s"]):
            self.assertTrue(_jam_allowed(hole, 169, 0.05), hole)

    def test_all_ins_over_a_single_raise_are_untouched(self):
        for hole in self.WEAK:
            self.assertTrue(_jam_allowed(hole, 400, 0.05, edge=1.0, level=1), hole)


class WeakHandWithAQuarterOfTheStackIn(unittest.TestCase):
    """Live round 41, hand 823: ace-high called 394 on the flop of a re-raised pot, then the rest."""
    BOARD = ["4s", "2d", "5h"]

    def test_ace_high_folds_once_the_call_commits_a_quarter_of_the_stack(self):
        state = _facing(["Ah", "Qd"], self.BOARD, 764, 394)
        saved = v4.PARAMS["commit_min"]
        v4.PARAMS["commit_min"] = 10 ** 9
        try:
            self.assertEqual(_act(state), "call")            # what it used to do
        finally:
            v4.PARAMS["commit_min"] = saved
        self.assertEqual(_act(state), "fold")

    def test_an_overpair_still_calls(self):
        self.assertEqual(_act(_facing(["Qs", "Qc"], self.BOARD, 764, 394)), "call")

    def test_a_small_pot_is_untouched(self):
        state = _facing(["Ah", "Qd"], self.BOARD, 150, 75)
        saved = v4.PARAMS["commit_min"]
        results = []
        for value in (saved, 10 ** 9):
            v4.PARAMS["commit_min"] = value
            results.append(_act(state))
        v4.PARAMS["commit_min"] = saved
        self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
