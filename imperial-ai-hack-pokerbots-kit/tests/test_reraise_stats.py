"""Light re-raises follow how often each seat has actually folded to them (live rounds 12-20)."""

import unittest

from src import preflop
from src.common import DEFAULT_PROFILE
from src.opponents import OpponentModel

ME, VILLAIN, OTHER, N = 2, 0, 4, 7
LIGHT = [["Kh", "7h"], ["Jc", "9d"], ["Ah", "4d"], ["Qs", "9s"], ["Td", "9d"], ["Kc", "8d"],
         ["Ac", "9d"], ["Qh", "Td"], ["Js", "6s"], ["Kd", "Jc"]]


def _blinds():
    return [{"seat": 0, "street": "preflop", "action": "small_blind", "amount": 10},
            {"seat": 1, "street": "preflop", "action": "big_blind", "amount": 20}]


def _act(seat, action, amount=0):
    return {"seat": seat, "street": "preflop", "action": action, "amount": amount}


def _open_then_3bet(answer, number):
    """The villain opens, another seat re-raises, the villain answers."""
    return {"type": "hand_end", "hand_number": number, "board": [], "shown": {},
            "history": _blinds() + [_act(VILLAIN, "raise", 60), _act(OTHER, "raise", 200),
                                    _act(VILLAIN, answer, 140 if answer == "call" else 0)]}


def _3bet_then_4bet(answer, number):
    """Another seat opens, the villain re-raises, the opener 4-bets, the villain answers."""
    return {"type": "hand_end", "hand_number": number, "board": [], "shown": {},
            "history": _blinds() + [_act(OTHER, "raise", 60), _act(VILLAIN, "raise", 200),
                                    _act(OTHER, "raise", 480),
                                    _act(VILLAIN, answer, 280 if answer == "call" else 0)]}


def _quiet(_answer, number):
    """Ordinary hands, so the villain looks like a normal player apart from the re-raise spots."""
    if number % 6 == 0:
        acts = [_act(VILLAIN, "raise", 60)]
    elif number % 6 == 1:
        acts = [_act(OTHER, "raise", 60), _act(VILLAIN, "call", 60)]
    else:
        acts = [_act(OTHER, "raise", 60), _act(VILLAIN, "fold")]
    return {"type": "hand_end", "hand_number": number, "board": [], "shown": {},
            "history": _blinds() + acts}


def _model(hands):
    model = OpponentModel()
    model.start({"num_players": N, "seat": ME})
    for i, (make, answer) in enumerate([(_quiet, None)] * 150 + hands):
        model.observe(make(answer, i + 1))
    return model


def _state(hole, villain_bet, my_bet, hist, to_call, min_raise_to, raises):
    stacks = [2000] * N
    bets = [0] * N
    bets[0], bets[1], bets[ME] = villain_bet, 20, my_bet
    for s in (0, 1, ME):
        stacks[s] -= bets[s]
    return {
        "street": "preflop", "seat": ME, "button": 6, "hole_cards": hole, "board": [],
        "stacks": stacks, "bets": bets, "folded": [s not in (0, ME) for s in range(N)],
        "pot": sum(bets), "to_call": to_call, "min_raise_to": min_raise_to, "max_raise_to": 2000,
        "legal_actions": ["fold", "call", "raise"], "small_blind": 10, "big_blind": 20,
        "blind_level": 0, "hand_number": 50, "betting": "no_limit", "raise_cap": None,
        "raises_this_street": raises, "history": hist,
    }


def _facing_3bet(hole):
    """We opened to 65, the small blind re-raised to 234, everyone else folded."""
    hist = _blinds() + [_act(ME, "raise", 65)] + [_act(s, "fold") for s in (3, 4, 5, 6)] + [
        _act(0, "raise", 234), _act(1, "fold")]
    return _state(hole, 234, 65, hist, 169, 403, 2)


def _facing_open(hole):
    """We are the button (seat 2). The villain opens to 60 from early position and it is folded to us,
    so only the two blinds are left to act behind us."""
    hist = [_act(3, "small_blind", 10), _act(4, "big_blind", 20), _act(5, "fold"), _act(6, "fold"),
            _act(0, "raise", 60), _act(1, "fold")]
    stacks = [2000] * N
    bets = [0] * N
    bets[3], bets[4], bets[0] = 10, 20, 60
    for s in (0, 3, 4):
        stacks[s] -= bets[s]
    return {
        "street": "preflop", "seat": ME, "button": 2, "hole_cards": hole, "board": [],
        "stacks": stacks, "bets": bets, "folded": [s in (1, 5, 6) for s in range(N)],
        "pot": 90, "to_call": 60, "min_raise_to": 100, "max_raise_to": 2000,
        "legal_actions": ["fold", "call", "raise"], "small_blind": 10, "big_blind": 20,
        "blind_level": 0, "hand_number": 50, "betting": "no_limit", "raise_cap": None,
        "raises_this_street": 1, "history": hist,
    }


def _small_raises(model, make_state):
    count = 0
    for hole in LIGHT:
        d = preflop.decide(make_state(hole), model.profiles())
        count += d.get("action") == "raise" and d.get("amount", 0) < 1500
    return count


class ReraiseStats(unittest.TestCase):
    def test_not_reported_until_seen_twice(self):
        p = _model([(_open_then_3bet, "fold"), (_3bet_then_4bet, "fold")]).profiles()[VILLAIN]
        self.assertNotIn("fold_to_3bet", p)
        self.assertNotIn("fold_to_4bet", p)
        self.assertNotIn("fold_to_3bet", dict(DEFAULT_PROFILE))
        self.assertNotIn("fold_to_4bet", dict(DEFAULT_PROFILE))

    def test_folders_read_high_and_callers_read_low(self):
        folder = _model([(_open_then_3bet, "fold")] * 12 + [(_3bet_then_4bet, "fold")] * 12).profiles()[VILLAIN]
        caller = _model([(_open_then_3bet, "call")] * 12 + [(_3bet_then_4bet, "call")] * 12).profiles()[VILLAIN]
        self.assertGreater(folder["fold_to_3bet"], 0.8)
        self.assertLess(caller["fold_to_3bet"], 0.3)
        self.assertGreater(folder["fold_to_4bet"], 0.7)
        self.assertLess(caller["fold_to_4bet"], 0.1)

    def test_the_seat_that_re_raised_is_not_counted_as_facing_it(self):
        p = _model([(_open_then_3bet, "fold")] * 6).profiles()
        self.assertNotIn("fold_to_3bet", p[OTHER])
        self.assertNotIn("fold_to_4bet", p[OTHER])

    def test_an_all_in_is_not_counted_as_a_re_raise(self):
        def jam(answer, number):
            h = _open_then_3bet(answer, number)
            h["history"][3] = _act(OTHER, "raise", 2000)
            return h
        self.assertNotIn("fold_to_3bet", _model([(jam, "fold")] * 6).profiles()[VILLAIN])


class LightReraisesFollowTheRecord(unittest.TestCase):
    # These check the estimate-driven rules underneath; the TT+/AK-only rule sits on top of them.
    def setUp(self):
        self._rr = preflop._RR_VALUE_ONLY
        preflop._RR_VALUE_ONLY = False

    def tearDown(self):
        preflop._RR_VALUE_ONLY = self._rr

    def test_fewer_light_4bets_into_a_seat_that_never_folds_to_them(self):
        never = _model([(_3bet_then_4bet, "call")] * 12)
        often = _model([(_3bet_then_4bet, "fold")] * 12)
        self.assertEqual(_small_raises(never, _facing_3bet), 0)
        self.assertGreater(_small_raises(often, _facing_3bet), _small_raises(never, _facing_3bet))

    def test_fewer_light_3bets_into_a_seat_that_never_folds_to_them(self):
        never = _model([(_open_then_3bet, "call")] * 12)
        often = _model([(_open_then_3bet, "fold")] * 12)
        self.assertGreater(_small_raises(often, _facing_open), _small_raises(never, _facing_open))

    def test_default_profiles_still_decide_legally(self):
        for hole in LIGHT:
            for make in (_facing_3bet, _facing_open):
                d = preflop.decide(make(hole), {})
                self.assertIn(d.get("action"), ("fold", "call", "raise"))


if __name__ == "__main__":
    unittest.main()
