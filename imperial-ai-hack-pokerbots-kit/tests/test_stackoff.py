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


def _facing_big_3bet(hole):
    """As jam_callers._facing_3bet, but the small blind re-raised to 305: 240 more to call."""
    state = jam_callers._facing_3bet(hole)
    state["stacks"][0], state["bets"][0] = 1695, 305
    state["pot"], state["to_call"], state["min_raise_to"] = 390, 240, 545
    state["history"][-2]["amount"] = 305
    return state


def _jams_big(hole, on=True, folds=8):
    saved = preflop._JAM_NEEDS_EDGE
    preflop._JAM_NEEDS_EDGE = on
    try:
        d = preflop.decide(_facing_big_3bet(hole), jam_callers._model(["fold"] * folds).profiles())
    finally:
        preflop._JAM_NEEDS_EDGE = saved
    return d.get("action") == "raise" and d.get("amount", 0) >= 1900


class AllInOverABigReraise(unittest.TestCase):
    WEAK = (["Ah", "Td"], ["Ah", "Jh"], ["Ad", "5s"], ["7d", "7s"], ["Jd", "8d"])

    def test_weak_aces_and_small_pairs_do_not_move_in(self):
        for hole in self.WEAK:
            self.assertFalse(_jams_big(hole), hole)

    def test_the_rule_is_what_stops_them(self):
        self.assertTrue(any(_jams_big(hole, on=False) for hole in self.WEAK))

    def test_big_hands_are_untouched(self):
        for hole in (["As", "Ac"], ["Kh", "Kc"], ["Ad", "Kd"], ["Ad", "Kc"], ["Th", "Tc"]):
            self.assertEqual(_jams_big(hole), _jams_big(hole, on=False), hole)

    def test_an_ordinary_reraise_is_untouched(self):
        for hole in (["Ah", "Td"], ["Ad", "5d"], ["7d", "7s"]):
            self.assertEqual(_jams(hole, folds=8), _jams(hole, on=False, folds=8), hole)


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
