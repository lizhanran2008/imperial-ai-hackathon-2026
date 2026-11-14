"""Opponent model: hand-counted features, decision-tree leaves, stability, house bots, timing."""

import importlib.util
import os
import random
import time
import unittest

from engine import FixedHandsTable
from engine.players import LocalPlayer
from src import exploits, opponents
from src.agent import Agent
from src.opponents import OpponentModel, classify

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_KEYS = ("hands", "vpip", "pfr", "three_bet", "aggression", "fold_to_bet", "showdown", "style")


def _a(seat, street, action, amount=0):
    return {"seat": seat, "street": street, "action": action, "amount": amount}


def _hand_one():
    """Seat 3 limps, seat 4 raises, seat 5 3-bets, seat 4 calls; seat 4 donk-bets the flop, seat 5
    raises, seat 4 folds."""
    return {
        "hand_number": 1, "board": ["2c", "7d", "Ks"], "shown": {}, "stacks": [2000] * 6,
        "history": [
            _a(1, "preflop", "small_blind", 10), _a(2, "preflop", "big_blind", 20),
            _a(3, "preflop", "call", 20), _a(4, "preflop", "raise", 60),
            _a(5, "preflop", "raise", 180), _a(0, "preflop", "fold"),
            _a(1, "preflop", "fold"), _a(2, "preflop", "fold"),
            _a(3, "preflop", "fold"), _a(4, "preflop", "call", 120),
            _a(4, "flop", "raise", 200), _a(5, "flop", "raise", 600), _a(4, "flop", "fold"),
        ],
    }


def _hand_two():
    """Seat 5 opens, seat 4 calls; seat 5 c-bets, seat 4 calls; turn checks through; seat 5 bets the
    river with a bluff, seat 4 calls, both show."""
    return {
        "hand_number": 2, "board": ["2c", "7d", "Ks", "9h", "3s"],
        "shown": {"4": ["Kd", "Qd"], "5": ["5h", "4h"]}, "stacks": [2000] * 6,
        "history": [
            _a(2, "preflop", "small_blind", 10), _a(3, "preflop", "big_blind", 20),
            _a(5, "preflop", "raise", 60), _a(0, "preflop", "fold"), _a(1, "preflop", "fold"),
            _a(2, "preflop", "fold"), _a(3, "preflop", "fold"), _a(4, "preflop", "call", 60),
            _a(4, "flop", "check"), _a(5, "flop", "raise", 80), _a(4, "flop", "call", 80),
            _a(4, "turn", "check"), _a(5, "turn", "check"),
            _a(4, "river", "check"), _a(5, "river", "raise", 150), _a(4, "river", "call", 150),
        ],
    }


class HandCountedFeatures(unittest.TestCase):
    def setUp(self):
        self.m = OpponentModel()
        self.m.start({"num_players": 6, "seat": 0, "starting_stack": 2000})
        self.m.observe(_hand_one())
        self.m.observe(_hand_two())
        self.c = self.m._counters

    def test_seat_3_limper(self):
        c = self.c[3]
        self.assertEqual((c.hands, c.vpip, c.pfr, c.unopened, c.limps), (2, 1, 0, 1, 1))
        self.assertEqual((c.three_bet_opps, c.three_bets, c.flops_seen), (1, 0, 0))

    def test_seat_4_raiser_who_folds_to_a_raise(self):
        c = self.c[4]
        self.assertEqual((c.hands, c.vpip, c.pfr, c.three_bet_opps, c.three_bets), (2, 2, 1, 1, 0))
        # Flop 1: bets (open spot), folds to the raise. Hand 2: two checks into nothing, then
        # faces the c-bet (call) and the river bet (call). Its own bet is never "facing a bet".
        self.assertEqual((c.faced_bet, c.folded_to_bet), (3, 1))
        self.assertEqual((c.agg_actions, c.passive_actions), (1, 2))
        self.assertEqual((c.open_spots, c.open_bets), (4, 1))
        self.assertEqual((c.cbet_opps, c.flops_seen, c.showdowns), (0, 2, 1))

    def test_seat_5_three_bettor_and_river_bluffer(self):
        c = self.c[5]
        self.assertEqual((c.hands, c.vpip, c.pfr, c.three_bet_opps, c.three_bets), (2, 2, 2, 1, 1))
        self.assertEqual((c.faced_bet, c.folded_to_bet), (1, 0))
        self.assertEqual((c.cbet_opps, c.cbets), (1, 1))   # hand 1 was donked into: no chance
        self.assertEqual((c.river_bets_shown, c.river_bluffs), (1, 1))
        self.assertEqual((c.flops_seen, c.showdowns), (2, 1))

    def test_rates_are_shrunk_toward_the_prior(self):
        p = self.m.profiles()[5]
        prior, w = opponents._PRIORS["pfr"]
        self.assertAlmostEqual(p["pfr"], round((2 + w * prior) / (2 + w), 4))
        self.assertLess(p["pfr"], 0.5)


class Contract(unittest.TestCase):
    def test_every_seat_has_the_contract_keys_from_the_first_hand(self):
        m = OpponentModel()
        m.start({"num_players": 8, "seat": 0})
        for prof in (m.profiles(), OpponentModel().profiles()):
            for p in prof.values():
                for k in CONTRACT_KEYS:
                    self.assertIn(k, p)
                self.assertEqual(p["style"], "unknown")
        self.assertEqual(set(m.profiles()), set(range(8)))

    def test_malformed_summaries_are_skipped(self):
        m = OpponentModel()
        m.start({"num_players": 4})
        for bad in (None, 3, {}, {"history": 7}, {"history": [None, {"seat": "x"}, 5]},
                    {"history": [_a(1, "flop", "raise", "lots")], "shown": {"x": 1}, "board": 9}):
            m.observe(bad)
        self.assertEqual(set(m.profiles()), set(range(4)))

    def test_style_is_always_a_valid_style(self):
        from src.common import VALID_STYLES
        self.assertTrue(set(opponents.ARCHETYPES.values()) <= set(VALID_STYLES))


def _feats(**kw):
    base = {"hands": 200, "vpip": 0.22, "pfr": 0.15, "three_bet": 0.06, "aggression": 0.55,
            "fold_to_bet": 0.45, "showdown": 0.3, "limp": 0.1, "jam": 0.01, "cbet": 0.6,
            "bet_open": 0.35, "river_bluff": 0.3}
    base.update(kw)
    return base


class DecisionTree(unittest.TestCase):
    def test_every_leaf_is_reachable(self):
        cases = {
            "unknown": _feats(hands=5),
            "shover": _feats(jam=0.25, pfr=0.3, vpip=0.4),
            "maniac": _feats(vpip=0.7, pfr=0.4, aggression=0.8),
            "calling_station": _feats(vpip=0.8, pfr=0.02, aggression=0.05, fold_to_bet=0.05, bet_open=0.02),
            "loose_passive": _feats(vpip=0.6, pfr=0.05, aggression=0.2, fold_to_bet=0.5, bet_open=0.1),
            "loose_aggressive": _feats(vpip=0.4, pfr=0.25),
            "tight_aggressive": _feats(),
            "nit": _feats(vpip=0.08, pfr=0.06),
            "weak_tight": _feats(pfr=0.08, aggression=0.2, bet_open=0.1, fold_to_bet=0.75),
            "tight_passive": _feats(pfr=0.08, aggression=0.2, bet_open=0.1),
        }
        self.assertEqual(set(cases), set(opponents.ARCHETYPES))
        for leaf, f in cases.items():
            self.assertEqual(classify(f), leaf, leaf)

    def test_one_odd_reading_does_not_flip_the_label(self):
        c = opponents._SeatCounters()
        c.update_archetype(_feats())
        odd = _feats(vpip=0.6, pfr=0.4, aggression=0.9)
        for _ in range(opponents._CONFIRM - 1):
            c.update_archetype(odd)
            self.assertEqual(c.archetype, "tight_aggressive")
        c.update_archetype(_feats())
        c.update_archetype(odd)
        self.assertEqual(c.archetype, "tight_aggressive")
        for _ in range(opponents._CONFIRM):
            c.update_archetype(odd)
        self.assertEqual(c.archetype, "maniac")


def _house(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(KIT, "examples", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Agent


class HouseBots(unittest.TestCase):
    EXPECT = {"tight_aggressive": "tight_aggressive", "calling_station": "calling_station",
              "random_bot": "maniac"}

    def test_labels_settle_within_100_hands_and_observe_is_fast(self):
        bots = {n: _house(n) for n in self.EXPECT}
        for seed in range(3):
            rng = random.Random(seed)
            names = [rng.choice(sorted(bots)) for _ in range(7)]
            me = LocalPlayer(Agent)
            FixedHandsTable([me] + [LocalPlayer(bots[n]) for n in names], hands=100, seed=seed).play()
            model = me.agent.model
            prof = model.profiles()
            for seat, name in enumerate(names, start=1):
                self.assertEqual(prof[seat]["archetype"], self.EXPECT[name], (seed, seat, name))

        # Timing against PROJECT.md budgets: observe 1 ms, profiles 0.1 ms on average.
        summary = _hand_two()
        t0 = time.perf_counter()
        for _ in range(200):
            model.observe(summary)
        observe_ms = (time.perf_counter() - t0) * 1000 / 200
        t0 = time.perf_counter()
        for _ in range(2000):
            model.profiles()
        profiles_ms = (time.perf_counter() - t0) * 1000 / 2000
        self.assertLess(observe_ms, 1.0)
        self.assertLess(profiles_ms, 0.1)


def _river_state(hole, board, to_call, pot=400, history=(), folded=None):
    folded = folded or [False, False] + [True] * 4
    return {
        "street": "river", "seat": 0, "button": 1, "hole_cards": hole, "board": board,
        "stacks": [1800] * 6, "bets": [0, to_call, 0, 0, 0, 0], "folded": folded,
        "pot": pot, "to_call": to_call, "min_raise_to": max(20, 2 * to_call), "max_raise_to": 1800,
        "legal_actions": (["fold", "call", "raise"] if to_call else ["check", "raise"]),
        "big_blind": 20, "raises_this_street": 1 if to_call else 0, "history": list(history),
    }


BOARD = ["2c", "7d", "Ks", "9h", "3s"]
BET = [_a(1, "river", "raise", 200)]


class CounterStrategies(unittest.TestCase):
    def setUp(self):
        exploits.seed(0)

    def prof(self, leaf, **kw):
        p = {"archetype": leaf, "fold_to_bet": 0.4, "river_bluff": 0.3}
        p.update(kw)
        return {1: p}

    def test_calls_a_maniac_down_with_top_pair(self):
        st = _river_state(["Kd", "5c"], BOARD, 200, history=BET)
        self.assertEqual(exploits.adjust(st, self.prof("maniac"), {"action": "fold"})["action"], "call")
        self.assertEqual(exploits.adjust(st, self.prof("tight_aggressive"), {"action": "fold"})["action"], "fold")

    def test_folds_a_weak_pair_to_a_station_bet(self):
        st = _river_state(["7c", "5c"], BOARD, 40, history=BET)
        self.assertEqual(exploits.adjust(st, self.prof("calling_station"), {"action": "call"})["action"], "fold")

    def test_never_bluffs_a_station_and_value_bets_thin(self):
        air = _river_state(["Jc", "Tc"], BOARD, 0)
        self.assertEqual(exploits.adjust(air, self.prof("calling_station"),
                                         {"action": "raise", "amount": 200})["action"], "check")
        mid = _river_state(["7c", "5c"], BOARD, 0)
        self.assertEqual(exploits.adjust(mid, self.prof("calling_station"), {"action": "check"})["action"], "raise")

    def test_bluffs_a_folder_heads_up(self):
        air = _river_state(["Jc", "Tc"], BOARD, 0)
        acts = [exploits.adjust(air, self.prof("nit", fold_to_bet=0.7), {"action": "check"})["action"]
                for _ in range(50)]
        self.assertGreater(acts.count("raise"), 30)
        multi = _river_state(["Jc", "Tc"], BOARD, 0, folded=[False] * 3 + [True] * 3)
        profs = {1: self.prof("nit")[1], 2: self.prof("nit")[1]}
        self.assertEqual(exploits.adjust(multi, profs, {"action": "check"})["action"], "check")

    def test_calls_a_known_river_bluffer(self):
        st = _river_state(["7c", "5c"], BOARD, 200, history=BET)
        p = self.prof("tight_aggressive", river_bluff=0.5)
        self.assertEqual(exploits.adjust(st, p, {"action": "fold"})["action"], "call")

    def test_preflop_and_disabled_pass_through(self):
        st = dict(_river_state(["Kd", "5c"], BOARD, 200, history=BET), street="preflop")
        self.assertEqual(exploits.adjust(st, self.prof("maniac"), {"action": "fold"}), {"action": "fold"})
        exploits.ENABLED = False
        try:
            st = _river_state(["Kd", "5c"], BOARD, 200, history=BET)
            self.assertEqual(exploits.adjust(st, self.prof("maniac"), {"action": "fold"}), {"action": "fold"})
        finally:
            exploits.ENABLED = True

    def test_bad_input_returns_the_action(self):
        self.assertEqual(exploits.adjust({}, None, {"action": "check"}), {"action": "check"})


if __name__ == "__main__":
    unittest.main()
