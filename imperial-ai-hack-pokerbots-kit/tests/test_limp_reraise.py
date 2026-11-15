"""Raises over a limp stop being wide once the limper is seen re-raising them (live round 24)."""

import unittest

from src import preflop
from src.common import DEFAULT_PROFILE
from src.opponents import OpponentModel

ME, VILLAIN, OTHER, N = 1, 6, 3, 8
JUNK = (["Jc", "4d"], ["Kh", "5s"], ["Qc", "4c"], ["9h", "8d"], ["Kd", "8s"], ["Ad", "8h"])
VALUE = (["As", "Ah"], ["Kc", "Kd"], ["Ad", "Qc"], ["9s", "9h"])


def _act(seat, action, amount=0):
    return {"seat": seat, "street": "preflop", "action": action, "amount": amount}


def _limp_hand(answer, number):
    """The villain limps, another seat raises, the villain answers."""
    amount = {"raise": 510, "call": 140}.get(answer, 0)
    return {"type": "hand_end", "hand_number": number, "board": [], "shown": {},
            "history": [_act(4, "small_blind", 10), _act(5, "big_blind", 20), _act(VILLAIN, "call", 20),
                        _act(7, "fold"), _act(0, "fold"), _act(OTHER, "raise", 160), _act(4, "fold"),
                        _act(5, "fold"), _act(VILLAIN, answer, amount)]}


def _model(answers):
    model = OpponentModel()
    model.start({"num_players": N, "seat": ME})
    for i, a in enumerate(answers):
        model.observe(_limp_hand(a, i + 1))
    return model


def _over_limp(hole):
    """The villain limps under the gun, it is folded to us on the button."""
    hist = [_act(2, "small_blind", 10), _act(3, "big_blind", 20), _act(4, "fold"), _act(5, "fold"),
            _act(VILLAIN, "call", 20), _act(7, "fold"), _act(0, "fold")]
    stacks = [2000] * N
    bets = [0] * N
    bets[2], bets[3], bets[VILLAIN] = 10, 20, 20
    for s in (2, 3, VILLAIN):
        stacks[s] -= bets[s]
    return {
        "street": "preflop", "seat": ME, "button": 1, "hole_cards": hole, "board": [],
        "stacks": stacks, "bets": bets, "folded": [s in (4, 5, 7, 0) for s in range(N)],
        "pot": 50, "to_call": 20, "min_raise_to": 40, "max_raise_to": 2000,
        "legal_actions": ["fold", "call", "raise"], "small_blind": 10, "big_blind": 20,
        "blind_level": 0, "hand_number": 50, "betting": "no_limit", "raise_cap": None,
        "raises_this_street": 0, "history": hist,
    }


def _raises(hands, model):
    return sum(preflop.decide(_over_limp(h), model.profiles()).get("action") == "raise" for h in hands)


class LimpReraiseStat(unittest.TestCase):
    def test_not_reported_until_seen_three_times(self):
        self.assertNotIn("limp_reraise", _model(["raise", "raise"]).profiles()[VILLAIN])
        self.assertNotIn("limp_reraise", dict(DEFAULT_PROFILE))

    def test_trapper_reads_high_and_ordinary_limper_reads_low(self):
        self.assertGreater(_model(["raise", "fold"] * 4).profiles()[VILLAIN]["limp_reraise"], 0.35)
        self.assertLess(_model(["call", "fold"] * 4).profiles()[VILLAIN]["limp_reraise"], 0.05)

    def test_only_the_limper_is_counted(self):
        profiles = _model(["raise"] * 5).profiles()
        self.assertNotIn("limp_reraise", profiles[OTHER])
        self.assertNotIn("limp_reraise", profiles[5])


class RaisesOverALimp(unittest.TestCase):
    def test_junk_stops_raising_into_a_trapper(self):
        self.assertEqual(_raises(JUNK, _model(["raise", "fold"] * 4)), 0)

    def test_big_hands_still_raise_into_a_trapper(self):
        self.assertEqual(_raises(VALUE, _model(["raise", "fold"] * 4)), len(VALUE))

    def test_an_ordinary_limper_is_treated_exactly_as_before(self):
        model = _model(["call", "fold"] * 4)
        stripped = model.profiles()
        for p in stripped.values():
            p.pop("limp_reraise", None)
        for hole in JUNK + VALUE:
            self.assertEqual(preflop.decide(_over_limp(hole), model.profiles()),
                             preflop.decide(_over_limp(hole), stripped), hole)

    def test_junk_did_raise_before_the_trap_was_seen(self):
        self.assertGreater(_raises(JUNK, _model([])), 0)


if __name__ == "__main__":
    unittest.main()
