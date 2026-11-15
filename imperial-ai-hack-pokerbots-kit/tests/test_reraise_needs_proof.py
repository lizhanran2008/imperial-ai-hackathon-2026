"""No light re-raise into a seat until it has been seen folding to re-raises (Sunday rounds 9-13)."""

import unittest

from src import preflop
from tests.test_reraise_stats import _facing_open, _model, _open_then_3bet, _small_raises


class LightReraiseNeedsProof(unittest.TestCase):
    def test_no_light_re_raise_into_a_seat_never_seen_facing_one(self):
        self.assertEqual(_small_raises(_model([]), _facing_open), 0)

    def test_a_seat_seen_folding_to_others_is_re_raised_light(self):
        self.assertGreater(_small_raises(_model([(_open_then_3bet, "fold")] * 8), _facing_open), 0)

    def test_a_seat_seen_calling_others_is_not(self):
        self.assertEqual(_small_raises(_model([(_open_then_3bet, "call")] * 8), _facing_open), 0)

    def test_big_hands_still_re_raise_an_unknown_seat(self):
        for hole in (["As", "Ac"], ["Kh", "Kc"]):
            d = preflop.decide(_facing_open(hole), _model([]).profiles())
            self.assertEqual(d.get("action"), "raise", hole)


if __name__ == "__main__":
    unittest.main()
