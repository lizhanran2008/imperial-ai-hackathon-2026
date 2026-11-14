"""Regression checks for src/postflop.py.

Run from imperial-ai-hack-pokerbots-kit/:  python3 -m unittest discover -s tests -v
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import handeval, postflop  # noqa: E402


def river_state(board, hole, pot=300, to_call=100, legal=("fold", "call")):
    """A heads-up river decision for seat 0 with the given cards and price."""
    return {
        "street": "river", "seat": 0, "button": 1, "hand_number": 1,
        "hole_cards": list(hole), "board": list(board),
        "pot": pot, "to_call": to_call, "legal_actions": list(legal),
        "bets": [0, to_call], "stacks": [1800, 1700], "folded": [False, False],
        "min_raise_to": None, "max_raise_to": None,
        "raises_this_street": 1 if to_call else 0,
        "small_blind": 10, "big_blind": 20, "betting": "no_limit", "raise_cap": None,
        "history": [],
    }


ROYAL = ["As", "Ks", "Qs", "Js", "Ts"]


class PlayingTheBoard(unittest.TestCase):
    def test_guaranteed_chop_is_never_folded(self):
        # Royal flush on the board: every player still in splits the pot.
        action = postflop.decide(river_state(ROYAL, ["2h", "8d"]), {})
        self.assertEqual(action, {"action": "call"})

    def test_guaranteed_chop_is_called_at_any_price(self):
        action = postflop.decide(river_state(ROYAL, ["2h", "8d"], pot=2300, to_call=2000), {})
        self.assertEqual(action, {"action": "call"})

    def test_guaranteed_chop_checks_when_nobody_has_bet(self):
        state = river_state(ROYAL, ["2h", "8d"], to_call=0, legal=("check",))
        self.assertEqual(postflop.decide(state, {}), {"action": "check"})

    def test_board_flush_that_one_card_beats_is_still_folded(self):
        # A-K-Q-J-9 of spades: any opponent holding the ten of spades wins.
        board = ["As", "Ks", "Qs", "Js", "9s"]
        self.assertFalse(postflop.board_unbeatable(board, ["2h", "8d"]))
        self.assertEqual(postflop.decide(river_state(board, ["2h", "8d"]), {}), {"action": "fold"})

    def test_board_straight_that_two_cards_beat_is_still_folded(self):
        # Broadway with three hearts: no single card beats it, two hearts do.
        board = ["Ah", "Kh", "Qh", "Jc", "Td"]
        self.assertFalse(postflop.board_unbeatable(board, ["2c", "8d"]))
        self.assertEqual(postflop.decide(river_state(board, ["2c", "8d"]), {}), {"action": "fold"})

    def test_board_straight_nobody_can_beat_is_called(self):
        # Broadway with no three cards of one suit: nothing beats it.
        board = ["Ah", "Kh", "Qc", "Jc", "Td"]
        self.assertTrue(postflop.board_unbeatable(board, ["2c", "8d"]))
        self.assertEqual(postflop.decide(river_state(board, ["2c", "8d"]), {}), {"action": "call"})

    def test_our_blockers_count(self):
        # Quad aces with a king: only a king kicker ties, nothing beats it.
        self.assertTrue(postflop.board_unbeatable(["Ac", "Ad", "Ah", "As", "Kd"], ["2c", "8d"]))
        # Quad aces with a queen: any king beats the board...
        self.assertFalse(postflop.board_unbeatable(["Ac", "Ad", "Ah", "As", "Qd"], ["2c", "8d"]))

    def test_matches_trying_every_pair_of_cards(self):
        # board_unbeatable skips most pairs; check it against trying them all.
        rng = random.Random(7)
        deck = [r + s for r in "23456789TJQKA" for s in "cdhs"]
        boards = [ROYAL, ["Ah", "Kh", "Qc", "Jc", "Td"], ["Ah", "Kh", "Qh", "Jc", "Td"],
                  ["Ac", "Ad", "Ah", "Ks", "Kd"], ["Kc", "Kd", "Kh", "As", "Ad"],
                  ["Ac", "Ad", "Ah", "As", "Kd"], ["9s", "8s", "7s", "6s", "5s"],
                  ["As", "Ks", "Qs", "Js", "9s"], ["5c", "4d", "3h", "2s", "Ad"]]
        boards += [rng.sample(deck, 5) for _ in range(40)]
        for board in boards:
            rest = [c for c in deck if c not in board]
            hole = rng.sample(rest, 2)
            live = [c for c in rest if c not in hole]
            base = handeval.rank(board)
            brute = not any(handeval.rank(board + [a, b]) > base
                            for i, a in enumerate(live) for b in live[i + 1:])
            postflop._unbeatable.clear()
            self.assertEqual(postflop.board_unbeatable(board, hole), brute, (board, hole))


if __name__ == "__main__":
    unittest.main()
