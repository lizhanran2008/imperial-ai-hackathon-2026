import glob
import json
import random

RANKS = "23456789TJQKA"


class OpponentModel:
    """Per-seat stats within a round: enters pots, raises, folds to bets, and showdowns."""

    def __init__(self, num_players=6):
        self.seats = {s: self._default_seat() for s in range(num_players)}


    def _default_seat(self):
        return {
            "hands": 20,          # Prior weight (k=20)
            "entered_pots": 6.0,  # VPIP prior (30%)
            "raises": 3.0,        # Raise prior (15%)
            "faced_bets": 10,
            "folded_to_bets": 4.5,# Fold-to-bet prior (45%)
            "showdown_sum": 0.5,  # Average showdown strength prior
            "showdowns": 1,
            "showdown_cards": [], # Cards shown down in this round
        }

    def get(self, seat):
        if seat not in self.seats:
            self.seats[seat] = self._default_seat()
        return self.seats[seat]

    def enter_pot_rate(self, seat):
        s = self.get(seat)
        return s["entered_pots"] / s["hands"]

    def raise_rate(self, seat):
        s = self.get(seat)
        return s["raises"] / s["hands"]

    def fold_to_bet_rate(self, seat):
        s = self.get(seat)
        return s["folded_to_bets"] / s["faced_bets"]

    def avg_showdown_strength(self, seat):
        s = self.get(seat)
        return s["showdown_sum"] / s["showdowns"]

    def update_from_hand(self, summary, my_seat):
        if not isinstance(summary, dict):
            return

        history = summary.get("history", summary.get("actions", []))
        entered, raised, faced_bet, folded = set(), set(), set(), set()
        bet_live = False

        for ev in history:
            if not isinstance(ev, dict):
                continue
            seat = ev.get("seat", ev.get("player"))
            act = ev.get("action", ev.get("type", ""))
            if seat is None:
                continue
            if seat == my_seat:
                if act in ("raise", "bet", "all_in"):
                    bet_live = True
                continue

            self.get(seat)
            if bet_live:
                faced_bet.add(seat)
                if act == "fold":
                    folded.add(seat)
            if act in ("call", "raise", "bet", "all_in"):
                entered.add(seat)
            if act in ("raise", "bet", "all_in"):
                raised.add(seat)
                bet_live = True

        for seat, s in self.seats.items():
            if seat == my_seat:
                continue
            s["hands"] += 1
            if seat in entered:
                s["entered_pots"] += 1
            if seat in raised:
                s["raises"] += 1
            if seat in faced_bet:
                s["faced_bets"] += 1
                if seat in folded:
                    s["folded_to_bets"] += 1

        shown = summary.get("shown_cards", summary.get("showdown", {}))
        if isinstance(shown, dict):
            for k, cards in shown.items():
                try:
                    seat = int(k)
                except (ValueError, TypeError):
                    continue
                if seat != my_seat and isinstance(cards, list) and len(cards) == 2:
                    s = self.get(seat)
                    s["showdown_cards"].append(cards)
                    r = sorted(RANKS.index(c[0]) for c in cards)
                    val = 0.85 if r[0] == r[1] else (r[1] + 0.5 * r[0]) / 18.0
                    s["showdown_sum"] += min(1.0, val)
                    s["showdowns"] += 1

    def exploit_adjustments(self, active_seats):
        """Returns threshold and sizing adjustments against active seats."""
        if not active_seats:
            return {"val_thresh": 0.0, "call_thresh": 0.0, "bluff_freq": 0.10, "bet_mult": 0.50}

        max_enter = max(self.enter_pot_rate(s) for s in active_seats)
        min_enter = min(self.enter_pot_rate(s) for s in active_seats)
        max_raise = max(self.raise_rate(s) for s in active_seats)
        min_fold = min(self.fold_to_bet_rate(s) for s in active_seats)
        min_sd = min(self.avg_showdown_strength(s) for s in active_seats)

        # Calling Station: enters many pots, rarely folds, or shows down weak hands
        if (max_enter > 0.45 and min_fold < 0.35) or min_sd < 0.38:
            return {"val_thresh": -0.08, "call_thresh": 0.0, "bluff_freq": 0.0, "bet_mult": 0.80}

        # Nit / Folder: rarely enters pots and folds often to bets
        if min_fold > 0.55 and min_enter < 0.25:
            return {"val_thresh": 0.05, "call_thresh": 0.15, "bluff_freq": 0.35, "bet_mult": 0.35}

        # Maniac: raises aggressively
        if max_raise > 0.28:
            return {"val_thresh": -0.05, "call_thresh": -0.12, "bluff_freq": 0.05, "bet_mult": 0.60}

        return {"val_thresh": 0.0, "call_thresh": 0.0, "bluff_freq": 0.10, "bet_mult": 0.50}


def analyze_fetched_hands(pattern="hands*.json*"):
    """Analyzes real hand logs downloaded by fetch_hands.py to extract player stats."""
    profiles = {}
    for path in glob.glob(pattern):
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                hands = [json.loads(line) for line in content.splitlines()] if "\n{" in content else json.loads(content)
                if isinstance(hands, dict):
                    hands = hands.get("hands", [hands])
        except Exception:
            continue

        for hand in hands:
            if not isinstance(hand, dict):
                continue
            history = hand.get("history", hand.get("actions", []))
            entered, raised, faced, folded = set(), set(), set(), set()
            seats = set()
            bet_live = False

            for ev in history:
                if not isinstance(ev, dict):
                    continue
                p = ev.get("team", ev.get("player", ev.get("seat")))
                act = ev.get("action", ev.get("type", ""))
                if p is None:
                    continue
                seats.add(p)
                if bet_live:
                    faced.add(p)
                    if act == "fold":
                        folded.add(p)
                if act in ("call", "raise", "bet", "all_in"):
                    entered.add(p)
                if act in ("raise", "bet", "all_in"):
                    raised.add(p)
                    bet_live = True

            for p in seats:
                st = profiles.setdefault(p, {"hands": 0, "enter": 0, "raise": 0, "faced": 0, "fold": 0})
                st["hands"] += 1
                st["enter"] += int(p in entered)
                st["raise"] += int(p in raised)
                st["faced"] += int(p in faced)
                st["fold"] += int(p in folded)

    return {
        p: {
            "enter_rate": d["enter"] / max(1, d["hands"]),
            "raise_rate": d["raise"] / max(1, d["hands"]),
            "fold_rate": d["fold"] / max(1, d["faced"]),
            "hands": d["hands"],
        }
        for p, d in profiles.items()
    }


class GauntletBot:
    """Parameterized bot that mimics real opponent archetypes for local_sim.py."""

    def __init__(self, enter_rate=0.30, raise_rate=0.15, fold_rate=0.45):
        self.rng = random.Random()
        self.enter_rate = enter_rate
        self.raise_rate = raise_rate
        self.fold_rate = fold_rate

    @classmethod
    def from_profile(cls, profile):
        return cls(profile["enter_rate"], profile["raise_rate"], profile["fold_rate"])

    def on_table_start(self, info):
        self.seat = info.get("seat", 0)

    def act(self, state):
        legal = state["legal_actions"]
        hole = state["hole_cards"]
        ranks = sorted(RANKS.index(c[0]) for c in hole)
        strength = 0.85 if ranks[0] == ranks[1] else (ranks[1] + 0.5 * ranks[0]) / 18.0

        if state.get("to_call", 0) > 0:
            if strength < self.fold_rate and self.rng.random() < self.fold_rate:
                return {"action": "fold" if "fold" in legal else "check"}

        if "raise" in legal and (strength > (1.0 - self.raise_rate) or self.rng.random() < self.raise_rate * 0.5):
            target = state["min_raise_to"] + state.get("pot", 0) // 2
            return {"action": "raise", "amount": min(target, state["max_raise_to"])}

        if "check" in legal:
            return {"action": "check"}

        if "call" in legal and (strength >= (1.0 - self.enter_rate) or self.rng.random() < self.enter_rate):
            return {"action": "call"}

        return {"action": "fold"}

    def on_hand_end(self, summary):
        pass


class CallingStationBot(GauntletBot):
    def __init__(self):
        super().__init__(enter_rate=0.75, raise_rate=0.05, fold_rate=0.15)


class NitBot(GauntletBot):
    def __init__(self):
        super().__init__(enter_rate=0.15, raise_rate=0.08, fold_rate=0.75)


class ManiacBot(GauntletBot):
    def __init__(self):
        super().__init__(enter_rate=0.65, raise_rate=0.45, fold_rate=0.25)


class Agent:
    def __init__(self):
        self.rng = random.Random()
        self.seat = 0
        self.opponents = OpponentModel()

    def on_table_start(self, info):
        self.seat = info.get("seat", 0)
        self.opponents = OpponentModel(info.get("num_players", 6))

    def _hand_strength(self, hole, board):
        hr = sorted(RANKS.index(c[0]) for c in hole)
        br = [RANKS.index(c[0]) for c in board]
        counts = {}
        for r in hr + br:
            counts[r] = counts.get(r, 0) + 1
        top = max(counts.values())
        pairs = sum(1 for v in counts.values() if v == 2)
        if top >= 3 or pairs >= 2:
            return 0.90
        if top == 2:
            if counts.get(hr[1], 0) == 2:
                return 0.72 + hr[1] / 50.0
            if counts.get(hr[0], 0) == 2:
                return 0.62 + hr[0] / 50.0
            return 0.38
        suited = 0.05 if hole[0][1] == hole[1][1] else 0.0
        return min(0.60, hr[1] * 0.035 + hr[0] * 0.015 + suited)

    def act(self, state):
        legal = state["legal_actions"]
        hole = state["hole_cards"]
        board = state.get("board", state.get("community_cards", []))
        pot = state.get("pot", 0)
        to_call = state.get("to_call", 0)
        bb = max(1, state.get("big_blind", 2))

        strength = self._hand_strength(hole, board)
        active = state.get("active_seats") or [s for s in self.opponents.seats if s != self.seat]
        adj = self.opponents.exploit_adjustments(active)

        if strength >= (0.60 + adj["val_thresh"]):
            if "raise" in legal:
                target = state["min_raise_to"] + int(pot * adj["bet_mult"])
                amt = max(state["min_raise_to"], min(target, state["max_raise_to"]))
                return {"action": "raise", "amount": amt}
            if "call" in legal:
                return {"action": "call"}

        if to_call == 0 and "raise" in legal and self.rng.random() < adj["bluff_freq"]:
            target = state["min_raise_to"] + int(pot * adj["bet_mult"])
            amt = max(state["min_raise_to"], min(target, state["max_raise_to"]))
            return {"action": "raise", "amount": amt}

        if "check" in legal:
            return {"action": "check"}

        cheap = to_call <= bb * 2 and strength >= 0.32
        if "call" in legal and (strength >= (0.48 + adj["call_thresh"]) or cheap):
            return {"action": "call"}

        return {"action": "fold"}

    def on_hand_end(self, summary):
        self.opponents.update_from_hand(summary, self.seat)