"""Opponent modelling module (owned by Davidlikestoprogram)."""

from . import common

_PREFLOP_STREETS = {"preflop", "pre", "0", 0}
_STREET_NAMES = {"preflop", "flop", "turn", "river", "deal_flop", "deal_turn", "deal_river"}
_BLIND_ACTIONS = {"sb", "bb", "small_blind", "big_blind", "blind", "ante", "post"}
_AGGRESSIVE_ACTIONS = {"bet", "raise", "all_in", "allin"}
_VOLUNTARY_PREFLOP_ACTIONS = {"call", "bet", "raise", "all_in", "allin"}
_DECISION_ACTIONS = {"fold", "check", "call", "bet", "raise", "all_in", "allin"}


class _SeatCounters:
    __slots__ = (
        "hands",
        "vpip",
        "pfr",
        "three_bet_opps",
        "three_bets",
        "agg_actions",
        "passive_actions",
        "faced_bet",
        "folded_to_bet",
        "flops_seen",
        "showdowns",
    )

    def __init__(self):
        self.hands = 0
        self.vpip = 0
        self.pfr = 0
        self.three_bet_opps = 0
        self.three_bets = 0
        self.agg_actions = 0
        self.passive_actions = 0
        self.faced_bet = 0
        self.folded_to_bet = 0
        self.flops_seen = 0
        self.showdowns = 0

    def to_profile(self):
        if self.hands == 0:
            return dict(common.DEFAULT_PROFILE)

        prior_w = 4.0
        d = common.DEFAULT_PROFILE

        vpip = (self.vpip + prior_w * d["vpip"]) / (self.hands + prior_w)
        pfr = (self.pfr + prior_w * d["pfr"]) / (self.hands + prior_w)
        three_bet = (self.three_bets + prior_w * d["three_bet"]) / (
            self.three_bet_opps + prior_w
        )

        total_post = self.agg_actions + self.passive_actions
        aggression = (self.agg_actions + prior_w * d["aggression"]) / (
            total_post + prior_w
        )

        fold_to_bet = (self.folded_to_bet + prior_w * d["fold_to_bet"]) / (
            self.faced_bet + prior_w
        )

        showdown = (self.showdowns + prior_w * d["showdown"]) / (
            self.flops_seen + prior_w
        )

        return {
            "hands": self.hands,
            "vpip": round(vpip, 4),
            "pfr": round(pfr, 4),
            "three_bet": round(three_bet, 4),
            "aggression": round(aggression, 4),
            "fold_to_bet": round(fold_to_bet, 4),
            "showdown": round(showdown, 4),
            "style": self._classify_style(vpip, pfr, aggression, three_bet),
        }

    def _classify_style(self, vpip, pfr, aggression, three_bet):
        if self.hands < 5:
            return "unknown"
        if vpip >= 0.52 and (aggression >= 0.55 or pfr >= 0.35 or three_bet >= 0.18):
            return "maniac"
        is_loose = vpip >= 0.30
        is_aggressive = aggression >= 0.42 or pfr >= 0.20
        if is_loose and is_aggressive:
            return "loose_aggressive"
        if is_loose and not is_aggressive:
            return "loose_passive"
        if not is_loose and is_aggressive:
            return "tight_aggressive"
        return "tight_passive"


class OpponentModel:
    """Per-round opponent tracker matching start(info), observe(summary), profiles()."""

    def __init__(self):
        self._num_players = 8
        self._hero_seat = None
        self._counters = {}
        self._profiles = {}

    def start(self, info):
        """Initialise table state once before the first hand."""
        if isinstance(info, dict):
            self._num_players = int(info.get("num_players", 8))
            self._hero_seat = info.get("seat")
        else:
            self._num_players = 8
            self._hero_seat = None

        self._counters = {
            seat: _SeatCounters() for seat in range(self._num_players)
        }
        self._profiles = {
            seat: dict(common.DEFAULT_PROFILE) for seat in range(self._num_players)
        }

    def _ensure_seat(self, seat):
        if not isinstance(seat, int) or seat < 0:
            return None
        c = self._counters.get(seat)
        if c is None:
            c = _SeatCounters()
            self._counters[seat] = c
            self._profiles[seat] = dict(common.DEFAULT_PROFILE)
        return c

    @staticmethod
    def _extract_item(item):
        if not isinstance(item, dict):
            return None, None, None
        seat = item.get("seat", item.get("player", item.get("actor")))
        action = item.get("action", item.get("type", item.get("move")))
        if isinstance(action, str):
            action = action.lower()
        street = item.get("street", item.get("round", item.get("stage")))
        if isinstance(street, str):
            street = street.lower()
        return seat, action, street

    def observe(self, summary):
        """Record a completed hand summary (never raises)."""
        if not isinstance(summary, dict):
            return

        if not self._counters:
            self.start({"num_players": self._num_players})

        dealt_seats = set()
        folded_seats = set()
        folded_preflop = set()
        vpip_this_hand = set()
        pfr_this_hand = set()
        three_bet_opp_this_hand = set()
        three_bet_this_hand = set()

        for key in ("dealt", "active_seats", "seats", "players"):
            val = summary.get(key)
            if isinstance(val, (list, tuple)):
                for item in val:
                    s = item.get("seat", item.get("id")) if isinstance(item, dict) else item
                    if isinstance(s, int):
                        dealt_seats.add(s)
        for key in ("stacks", "payoffs", "winnings", "deltas"):
            val = summary.get(key)
            if isinstance(val, dict):
                for s in val:
                    if isinstance(s, int):
                        dealt_seats.add(s)
            elif isinstance(val, list):
                for idx, amt in enumerate(val):
                    if amt is not None:
                        dealt_seats.add(idx)

        history = summary.get("history") or summary.get("actions") or []
        current_street = "preflop"
        preflop_raises = 0
        street_has_bet = False
        last_board_len = 0

        for item in history:
            if not isinstance(item, dict):
                continue

            seat, action, ev_street = self._extract_item(item)
            board = item.get("board", item.get("community_cards"))
            board_len = len(board) if isinstance(board, (list, tuple)) else last_board_len

            new_street = None
            if ev_street is not None:
                new_street = "preflop" if ev_street in _PREFLOP_STREETS else str(ev_street)
            elif action in _STREET_NAMES:
                new_street = "preflop" if "pre" in action else action.replace("deal_", "")
            elif board_len != last_board_len:
                last_board_len = board_len
                if board_len == 3:
                    new_street = "flop"
                elif board_len == 4:
                    new_street = "turn"
                elif board_len >= 5:
                    new_street = "river"

            if new_street is not None and new_street != current_street:
                current_street = new_street
                # Reset active bet state when changing streets
                street_has_bet = False

            sub_actions = item.get("actions")
            if isinstance(sub_actions, list):
                for sub in sub_actions:
                    s_seat, s_act, _ = self._extract_item(sub)
                    street_has_bet, preflop_raises = self._record_action(
                        s_seat,
                        s_act,
                        current_street,
                        street_has_bet,
                        preflop_raises,
                        dealt_seats,
                        folded_seats,
                        folded_preflop,
                        vpip_this_hand,
                        pfr_this_hand,
                        three_bet_opp_this_hand,
                        three_bet_this_hand,
                    )
                continue

            street_has_bet, preflop_raises = self._record_action(
                seat,
                action,
                current_street,
                street_has_bet,
                preflop_raises,
                dealt_seats,
                folded_seats,
                folded_preflop,
                vpip_this_hand,
                pfr_this_hand,
                three_bet_opp_this_hand,
                three_bet_this_hand,
            )

        # Read summary["shown"] across dict or list representations
        shown_seats = set()
        shown_raw = summary.get("shown")
        if isinstance(shown_raw, dict):
            for s, cards in shown_raw.items():
                try:
                    s_idx = int(s)
                except (TypeError, ValueError):
                    continue
                if cards:
                    shown_seats.add(s_idx)
                    dealt_seats.add(s_idx)
        elif isinstance(shown_raw, (list, tuple)):
            for idx, entry in enumerate(shown_raw):
                if isinstance(entry, dict):
                    s_idx = entry.get("seat", entry.get("player"))
                    cards = entry.get("cards", entry.get("hand", entry.get("hole_cards")))
                    if isinstance(s_idx, int) and cards:
                        shown_seats.add(s_idx)
                        dealt_seats.add(s_idx)
                elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    shown_seats.add(idx)
                    dealt_seats.add(idx)
                elif isinstance(entry, int):
                    shown_seats.add(entry)
                    dealt_seats.add(entry)

        board = summary.get("board")
        reached_flop = isinstance(board, (list, tuple)) and len(board) >= 3
        for seat in dealt_seats:
            c = self._ensure_seat(seat)
            if c is None:
                continue
            c.hands += 1
            if seat in vpip_this_hand:
                c.vpip += 1
            if seat in pfr_this_hand:
                c.pfr += 1
            if seat in three_bet_opp_this_hand:
                c.three_bet_opps += 1
            if seat in three_bet_this_hand:
                c.three_bets += 1
            if reached_flop and seat not in folded_preflop:
                c.flops_seen += 1
                if seat in shown_seats and seat not in folded_seats:
                    c.showdowns += 1
            self._profiles[seat] = c.to_profile()

    def _record_action(
        self,
        seat,
        action,
        current_street,
        street_has_bet,
        preflop_raises,
        dealt_seats,
        folded_seats,
        folded_preflop,
        vpip_this_hand,
        pfr_this_hand,
        three_bet_opp_this_hand,
        three_bet_this_hand,
    ):
        if not isinstance(seat, int) or not action:
            return street_has_bet, preflop_raises

        if action in _BLIND_ACTIONS:
            dealt_seats.add(seat)
            return street_has_bet, preflop_raises

        if action not in _DECISION_ACTIONS:
            return street_has_bet, preflop_raises

        # Keep folded seats strictly out of active decisions
        if seat in folded_seats:
            return street_has_bet, preflop_raises

        dealt_seats.add(seat)
        c = self._ensure_seat(seat)
        if c is None:
            return street_has_bet, preflop_raises

        is_preflop = current_street in _PREFLOP_STREETS

        # Only preflop actions modify preflop entry/raise counters
        if is_preflop:
            if action in _VOLUNTARY_PREFLOP_ACTIONS:
                vpip_this_hand.add(seat)
            if preflop_raises == 1:
                three_bet_opp_this_hand.add(seat)
            if action in _AGGRESSIVE_ACTIONS:
                pfr_this_hand.add(seat)
                if preflop_raises == 1:
                    three_bet_this_hand.add(seat)
                preflop_raises += 1

        if not is_preflop:
            if street_has_bet and action != "check":
                c.faced_bet += 1
                if action == "fold":
                    c.folded_to_bet += 1
            if action == "call":
                c.passive_actions += 1
            elif action in _AGGRESSIVE_ACTIONS:
                c.agg_actions += 1
                street_has_bet = True

        if action == "fold":
            folded_seats.add(seat)
            if is_preflop:
                folded_preflop.add(seat)

        return street_has_bet, preflop_raises

    def profiles(self):
        """Return per-seat profile dicts for all seats at the table."""
        if not self._profiles:
            return {
                seat: dict(common.DEFAULT_PROFILE) for seat in range(self._num_players)
            }
        return {seat: dict(prof) for seat, prof in self._profiles.items()}


_DEFAULT_MODEL = OpponentModel()


def start(info):
    """Module-level start(info) helper delegating to default OpponentModel."""
    _DEFAULT_MODEL.start(info)


def observe(summary):
    """Module-level observe(summary) helper delegating to default OpponentModel."""
    _DEFAULT_MODEL.observe(summary)


def profiles():
    """Module-level profiles() helper delegating to default OpponentModel."""
    return _DEFAULT_MODEL.profiles()