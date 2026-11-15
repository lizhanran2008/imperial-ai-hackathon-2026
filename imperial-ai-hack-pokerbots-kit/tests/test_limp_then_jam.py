"""After limping, only TT+ and AK call an all-in (live round 26, hand 308)."""

import unittest

from src import preflop

ME, N = 1, 8


def _act(seat, action, amount=0):
    return {"seat": seat, "street": "preflop", "action": action, "amount": amount}


def _state(hole, jam=2000, we_limped=True):
    """Seat 6 limps, we limp (or not), seat 3 raises to 90, seat 6 moves all-in."""
    hist = [_act(4, "small_blind", 10), _act(5, "big_blind", 20), _act(6, "call", 20), _act(7, "fold"),
            _act(0, "fold")]
    if we_limped:
        hist.append(_act(ME, "call", 20))
    hist += [_act(2, "fold"), _act(3, "raise", 90), _act(4, "fold"), _act(5, "fold"), _act(6, "raise", jam)]
    mine = 20 if we_limped else 0
    bets = [0, mine, 0, 90, 10, 20, jam, 0]
    stacks = [2000 - b for b in bets]
    return {
        "street": "preflop", "seat": ME, "button": 3, "hole_cards": hole, "board": [],
        "stacks": stacks, "bets": bets, "folded": [s in (0, 2, 4, 5, 7) for s in range(N)],
        "pot": sum(bets), "to_call": jam - mine, "min_raise_to": 2000, "max_raise_to": 2000,
        "legal_actions": ["fold", "call"] if jam >= 2000 else ["fold", "call", "raise"],
        "small_blind": 10, "big_blind": 20, "blind_level": 0, "hand_number": 308,
        "betting": "no_limit", "raise_cap": None, "raises_this_street": 2, "history": hist,
    }


class LimpThenJam(unittest.TestCase):
    def test_limped_hands_fold_to_an_all_in(self):
        for hole in (["5d", "5h"], ["7c", "7h"], ["Ac", "Tc"], ["Ac", "Jh"], ["Kc", "Qh"], ["9c", "9h"]):
            self.assertEqual(preflop.decide(_state(hole), {}).get("action"), "fold", hole)

    def test_big_bet_short_of_all_in_also_folds(self):
        self.assertEqual(preflop.decide(_state(["5d", "5h"], jam=800), {}).get("action"), "fold")

    def test_strong_hands_are_left_to_the_normal_logic(self):
        for hole in (["Ac", "Ah"], ["Kc", "Kh"], ["Ac", "Kc"], ["Ac", "Kh"], ["Tc", "Th"]):
            with_rule = preflop.decide(_state(hole), {})
            keep = preflop._LIMP_JAM
            preflop._LIMP_JAM = 99.0
            try:
                without = preflop.decide(_state(hole), {})
            finally:
                preflop._LIMP_JAM = keep
            self.assertEqual(with_rule, without, hole)
        self.assertEqual(preflop.decide(_state(["Ac", "Ah"]), {}).get("action"), "call")

    def test_no_effect_when_we_did_not_limp(self):
        for hole in (["5d", "5h"], ["Ac", "Tc"], ["9c", "9h"]):
            with_rule = preflop.decide(_state(hole, we_limped=False), {})
            keep = preflop._LIMP_JAM
            preflop._LIMP_JAM = 99.0
            try:
                without = preflop.decide(_state(hole, we_limped=False), {})
            finally:
                preflop._LIMP_JAM = keep
            self.assertEqual(with_rule, without, hole)


if __name__ == "__main__":
    unittest.main()
