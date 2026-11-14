"""Opponent modelling module (owned by Davidlikestoprogram).

Three steps, run after every hand of a round (the same seats play all 1,000 hands):

1. Features. Each hand's history is replayed and per-seat counters are updated:
   how often a seat enters the pot, raises, re-raises, limps, moves all in
   preflop, bets or raises postflop, folds to a bet, continuation-bets, reaches
   showdown, and how often its river bets turn out to be bluffs when its cards
   are shown. Every rate starts at a population prior and moves toward the
   observed value as evidence accumulates (`rate = (hits + w*prior) / (n + w)`),
   so one unusual hand cannot swing a seat.

2. Archetype. `classify(profile)` is a small hand-built decision tree over those
   features (there is no labelled data to train one on). Its leaves are listed
   in ARCHETYPES. A seat only switches leaf once the tree has given the new leaf
   for `_CONFIRM` hands in a row, so the label is stable from hand to hand.

3. Contract. profiles() returns the profile dict defined in PROJECT.md (vpip,
   pfr, three_bet, aggression, fold_to_bet, showdown, style), plus additive
   keys: limp, jam, cbet, river_bluff, archetype, and call_jam once seen twice.
   The counter-strategy for each archetype lives in src/exploits.py.
"""

from . import common, handeval

_PREFLOP_STREETS = {"preflop", "pre", "0", 0}
_STREET_NAMES = {"preflop", "flop", "turn", "river", "deal_flop", "deal_turn", "deal_river"}
_BLIND_ACTIONS = {"sb", "bb", "small_blind", "big_blind", "blind", "ante", "post"}
_AGGRESSIVE_ACTIONS = {"bet", "raise", "all_in", "allin"}
_VOLUNTARY_PREFLOP_ACTIONS = {"call", "bet", "raise", "all_in", "allin"}
_DECISION_ACTIONS = {"fold", "check", "call", "bet", "raise", "all_in", "allin"}

_CJ_PRIOR = 0.35     # prior share of preflop all-ins a seat calls after raising itself
_CJ_PRIOR_W = 3.0    # weight of that prior, in observations
_CJ_MIN = 2          # observations needed before the frequency is reported
_JAM_BB = 40         # a preflop raise to at least this many big blinds counts as all-in

# Feature priors: name -> (population default, weight in observations).
_PRIORS = {
    "vpip": (common.DEFAULT_PROFILE["vpip"], 4.0),
    "pfr": (common.DEFAULT_PROFILE["pfr"], 4.0),
    "three_bet": (common.DEFAULT_PROFILE["three_bet"], 4.0),
    "aggression": (common.DEFAULT_PROFILE["aggression"], 4.0),
    "fold_to_bet": (common.DEFAULT_PROFILE["fold_to_bet"], 4.0),
    "showdown": (common.DEFAULT_PROFILE["showdown"], 4.0),
    "limp": (0.10, 4.0),         # share of unopened pots entered by calling
    "jam": (0.02, 10.0),         # share of hands with a preflop all-in raise
    "cbet": (0.60, 3.0),         # share of flops the preflop raiser bets when first to bet
    "bet_open": (0.30, 4.0),     # share of postflop spots with no bet in front where the seat bets
    "river_bluff": (0.30, 3.0),  # share of shown river bets made with a pair below top pair or less
}

# Decision-tree leaves -> contract `style` (common.VALID_STYLES).
ARCHETYPES = {
    "unknown": "unknown",
    "shover": "maniac",              # most of its preflop raises are all-ins
    "maniac": "maniac",              # plays most hands and bets/raises most of them
    "calling_station": "loose_passive",  # plays many hands, calls, rarely folds to a bet
    "loose_passive": "loose_passive",    # plays many hands passively but does give up
    "loose_aggressive": "loose_aggressive",
    "tight_aggressive": "tight_aggressive",
    "nit": "tight_passive",          # plays very few hands
    "weak_tight": "tight_passive",   # tight, passive and folds to most bets
    "tight_passive": "tight_passive",
}

_MIN_HANDS = 15   # below this every seat is "unknown"
_CONFIRM = 5      # hands in a row the tree must give a new leaf before the seat switches

_BLUFF_MADE = {"high_card", "board", "board_pair", "board_two_pair", "board_trips",
               "bottom_pair", "middle_pair", "underpair"}


def classify(p):
    """Decision tree: profile dict (smoothed features) -> archetype name."""
    if p.get("hands", 0) < _MIN_HANDS:
        return "unknown"
    vpip, pfr, agg, ftb = p["vpip"], p["pfr"], p["aggression"], p["fold_to_bet"]
    aggressive = agg >= 0.40 or pfr >= 0.18 or p["bet_open"] >= 0.25
    if p["jam"] >= 0.12 and p["jam"] >= 0.5 * pfr:
        return "shover"
    if vpip >= 0.50:
        if agg >= 0.50 or pfr >= 0.30 or p["three_bet"] >= 0.18:
            return "maniac"
        return "calling_station" if ftb <= 0.30 else "loose_passive"
    if vpip >= 0.34:
        if aggressive:
            return "loose_aggressive"
        return "calling_station" if ftb <= 0.25 else "loose_passive"
    if vpip < 0.12:
        return "nit"
    if aggressive:
        return "tight_aggressive"
    return "weak_tight" if ftb >= 0.62 else "tight_passive"


class _SeatCounters:
    __slots__ = (
        "hands", "vpip", "pfr", "three_bet_opps", "three_bets",
        "unopened", "limps", "jams",
        "agg_actions", "passive_actions", "faced_bet", "folded_to_bet",
        "cbet_opps", "cbets", "open_spots", "open_bets", "flops_seen", "showdowns",
        "river_bets_shown", "river_bluffs",
        "jam_faced", "jam_called",
        "archetype", "pending", "pending_n",
    )

    def __init__(self):
        for name in self.__slots__:
            setattr(self, name, 0)
        self.archetype = "unknown"
        self.pending = "unknown"

    @staticmethod
    def _rate(name, hits, n):
        prior, w = _PRIORS[name]
        return round((hits + w * prior) / (n + w), 4)

    def features(self):
        r = self._rate
        return {
            "hands": self.hands,
            "vpip": r("vpip", self.vpip, self.hands),
            "pfr": r("pfr", self.pfr, self.hands),
            "three_bet": r("three_bet", self.three_bets, self.three_bet_opps),
            "aggression": r("aggression", self.agg_actions,
                            self.agg_actions + self.passive_actions),
            "fold_to_bet": r("fold_to_bet", self.folded_to_bet, self.faced_bet),
            "showdown": r("showdown", self.showdowns, self.flops_seen),
            "limp": r("limp", self.limps, self.unopened),
            "jam": r("jam", self.jams, self.hands),
            "cbet": r("cbet", self.cbets, self.cbet_opps),
            "bet_open": r("bet_open", self.open_bets, self.open_spots),
            "river_bluff": r("river_bluff", self.river_bluffs, self.river_bets_shown),
        }

    def update_archetype(self, feats):
        leaf = classify(feats)
        if leaf == self.archetype or self.archetype == "unknown" or leaf == "unknown":
            # First real label is taken at once (the hand minimum already gates it).
            self.archetype, self.pending, self.pending_n = leaf, leaf, 0
            return
        if leaf == self.pending:
            self.pending_n += 1
        else:
            self.pending, self.pending_n = leaf, 1
        if self.pending_n >= _CONFIRM:
            self.archetype, self.pending_n = leaf, 0

    def to_profile(self):
        if self.hands == 0:
            out = dict(common.DEFAULT_PROFILE)
            out.update({k: v[0] for k, v in _PRIORS.items() if k not in out})
            out["archetype"] = "unknown"
            return out
        out = {}
        if self.jam_faced >= _CJ_MIN:
            out["call_jam"] = round(
                (self.jam_called + _CJ_PRIOR_W * _CJ_PRIOR) / (self.jam_faced + _CJ_PRIOR_W), 4)
        out.update(self.features())
        out["archetype"] = self.archetype
        out["style"] = ARCHETYPES[self.archetype]
        return out


class OpponentModel:
    """Per-round opponent tracker matching start(info), observe(summary), profiles()."""

    def __init__(self):
        self._num_players = 8
        self._hero_seat = None
        self._stack0 = 0
        self._counters = {}
        self._profiles = {}

    def start(self, info):
        """Initialise table state once before the first hand."""
        info = info if isinstance(info, dict) else {}
        try:
            self._num_players = int(info.get("num_players", 8))
        except (TypeError, ValueError):
            self._num_players = 8
        self._hero_seat = info.get("seat")
        try:
            self._stack0 = float(info.get("starting_stack") or 0)
        except (TypeError, ValueError):
            self._stack0 = 0
        self._counters = {s: _SeatCounters() for s in range(self._num_players)}
        self._profiles = {s: self._counters[s].to_profile() for s in range(self._num_players)}

    def _ensure_seat(self, seat):
        if not isinstance(seat, int) or seat < 0:
            return None
        c = self._counters.get(seat)
        if c is None:
            c = _SeatCounters()
            self._counters[seat] = c
            self._profiles[seat] = c.to_profile()
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

    @staticmethod
    def _amount(item):
        try:
            return float(item.get("amount") or 0)
        except (TypeError, ValueError, AttributeError):
            return 0.0

    def _record_jam_calls(self, history):
        """Count how each seat that had raised preflop answers a later preflop all-in."""
        bb = 0
        raisers = set()
        jam_by = None
        for item in history:
            seat, action, street = self._extract_item(item)
            if street is not None and street not in _PREFLOP_STREETS:
                break
            amount = self._amount(item) if isinstance(item, dict) else 0.0
            if action in _BLIND_ACTIONS:
                bb = max(bb, amount)
                continue
            if not isinstance(seat, int) or action not in _DECISION_ACTIONS:
                continue
            if jam_by is not None and seat != jam_by and seat in raisers:
                c = self._ensure_seat(seat)
                if c is not None and action != "check":
                    c.jam_faced += 1
                    if action != "fold":
                        c.jam_called += 1
                raisers.discard(seat)
                if action in _AGGRESSIVE_ACTIONS:
                    continue
            if action in _AGGRESSIVE_ACTIONS:
                raisers.add(seat)
                if action in ("all_in", "allin") or (bb > 0 and amount >= _JAM_BB * bb):
                    jam_by = seat
                    raisers.discard(seat)

    def observe(self, summary):
        """Record a completed hand summary. Never raises; a malformed summary is skipped."""
        if not isinstance(summary, dict):
            return
        if not self._counters:
            self.start({"num_players": self._num_players})
        history = summary.get("history") or summary.get("actions") or []
        if not isinstance(history, (list, tuple)):
            return
        try:
            self._record_jam_calls(history)
        except Exception:
            pass
        try:
            self._observe(summary, history)
        except Exception:
            pass

    def _observe(self, summary, history):
        dealt = set()
        stacks = summary.get("stacks")
        if isinstance(stacks, list):
            dealt.update(i for i, s in enumerate(stacks) if s is not None)

        vpip, pfr, jams, tb_opp, tb = set(), set(), set(), set(), set()
        acted_pf, folded, folded_pf = set(), set(), set()
        street, bb, last_board = "preflop", 0.0, 0
        pf_raises, pf_aggr = 0, None
        st_aggr, flop_bet_made = None, False
        river_aggr = None

        for item in history:
            if not isinstance(item, dict):
                continue
            seat, action, ev_street = self._extract_item(item)

            new_street = None
            if ev_street is not None:
                new_street = "preflop" if ev_street in _PREFLOP_STREETS else str(ev_street)
            elif action in _STREET_NAMES:
                new_street = "preflop" if "pre" in action else action.replace("deal_", "")
            else:
                board = item.get("board", item.get("community_cards"))
                if isinstance(board, (list, tuple)) and len(board) != last_board:
                    last_board = len(board)
                    new_street = {3: "flop", 4: "turn"}.get(last_board, "river")
            if new_street is not None and new_street != street:
                street, st_aggr = new_street, None

            if not isinstance(seat, int) or not action:
                continue
            amount = self._amount(item)
            if action in _BLIND_ACTIONS:
                dealt.add(seat)
                bb = max(bb, amount)
                continue
            if action not in _DECISION_ACTIONS or seat in folded:
                continue
            c = self._ensure_seat(seat)
            if c is None:
                continue
            dealt.add(seat)
            aggressive = action in _AGGRESSIVE_ACTIONS

            if street == "preflop":
                if seat not in acted_pf and pf_raises == 0 and action != "check":
                    c.unopened += 1
                    if action == "call":
                        c.limps += 1
                acted_pf.add(seat)
                if action in _VOLUNTARY_PREFLOP_ACTIONS:
                    vpip.add(seat)
                if pf_raises == 1 and seat != pf_aggr:
                    tb_opp.add(seat)
                if aggressive:
                    pfr.add(seat)
                    if pf_raises == 1 and seat != pf_aggr:
                        tb.add(seat)
                    if action in ("all_in", "allin") or (bb > 0 and amount >= _JAM_BB * bb) or \
                            (self._stack0 > 0 and amount >= 0.9 * self._stack0):
                        jams.add(seat)
                    pf_raises += 1
                    pf_aggr = seat
            else:
                if st_aggr is not None and st_aggr != seat:
                    c.faced_bet += 1
                    if action == "fold":
                        c.folded_to_bet += 1
                elif st_aggr is None:
                    c.open_spots += 1
                    if aggressive:
                        c.open_bets += 1
                if street == "flop" and seat == pf_aggr and not flop_bet_made:
                    c.cbet_opps += 1
                    if aggressive:
                        c.cbets += 1
                if action == "call":
                    c.passive_actions += 1
                elif aggressive:
                    c.agg_actions += 1
                    st_aggr = seat
                    if street == "flop":
                        flop_bet_made = True
                    if street == "river":
                        river_aggr = seat
                if street == "flop" and seat == pf_aggr:
                    pf_aggr = None   # the c-bet chance is used up either way

            if action == "fold":
                folded.add(seat)
                if street == "preflop":
                    folded_pf.add(seat)

        shown = {}
        raw = summary.get("shown")
        if isinstance(raw, dict):
            for s, cards in raw.items():
                try:
                    shown[int(s)] = cards
                except (TypeError, ValueError):
                    continue
        board = summary.get("board")
        board = list(board) if isinstance(board, (list, tuple)) else []
        dealt.update(s for s, cards in shown.items() if cards)

        if river_aggr is not None and len(board) == 5 and shown.get(river_aggr):
            c = self._ensure_seat(river_aggr)
            try:
                made = handeval.describe(list(shown[river_aggr]), board)["made"]
                c.river_bets_shown += 1
                if made in _BLUFF_MADE:
                    c.river_bluffs += 1
            except Exception:
                pass

        reached_flop = len(board) >= 3
        for seat in dealt:
            c = self._ensure_seat(seat)
            if c is None:
                continue
            c.hands += 1
            c.vpip += seat in vpip
            c.pfr += seat in pfr
            c.jams += seat in jams
            c.three_bet_opps += seat in tb_opp
            c.three_bets += seat in tb
            if reached_flop and seat not in folded_pf:
                c.flops_seen += 1
                if shown.get(seat) and seat not in folded:
                    c.showdowns += 1
            c.update_archetype(c.features())
            self._profiles[seat] = c.to_profile()

    def profiles(self):
        """Return per-seat profile dicts for all seats at the table."""
        if not self._profiles:
            return {s: _SeatCounters().to_profile() for s in range(self._num_players)}
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
