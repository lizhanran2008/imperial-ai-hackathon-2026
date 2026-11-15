"""Tournament Agent entrypoint integrating opponent model and strategy modules."""

from . import common, handeval, postflop, postflop_ranges_v4, preflop
from .opponents import OpponentModel


# Sunday rounds 1-11: calling a bet of two thirds of the pot or more on the flop or turn with no pair
# and no strong draw, in a pot with at most one preflop raise, lost chips in 8 rounds out of 9.
_AIR = ("high_card", "board", "board_pair", "board_two_pair", "board_trips")
_AIR_BET = 0.40     # the call as a share of the pot including the bet (0.40 is a two-thirds-pot bet)


def _hopeless_call(state):
    """True for a flop/turn call with nothing against a sizeable bet in a pot raised at most once."""
    if state.get("street") not in ("flop", "turn"):
        return False
    pot = state.get("pot", 0)
    if pot <= 0 or state.get("to_call", 0) < _AIR_BET * pot:
        return False
    raises = 0
    for a in state.get("history", ()):
        if a.get("street") == "preflop" and a.get("action") == "raise":
            raises += 1
    if raises >= 2:
        return False
    d = handeval.describe(state["hole_cards"], state["board"])
    return d["made"] in _AIR and not d["flush_draw"] and d["straight_draw"] != "open_ended"


class Agent:
    """AlgoSoc Pokerbots Agent delegating to preflop/postflop/opponent modules."""

    def __init__(self):
        self.seat = None
        self.model = OpponentModel()

    def on_table_start(self, info):
        """Initialise the opponent model and postflop learner for this round."""
        self.seat = info.get("seat") if isinstance(info, dict) else None
        self.model = OpponentModel()
        self.model.start(info)
        if isinstance(self.seat, int):
            postflop_ranges_v4.start_table(self.seat, int(info.get("num_players", 8)))

    def act(self, state):
        """Route decision to preflop/postflop and enforce legal action safety."""
        try:
            profiles = self.model.profiles()
            if state.get("street") == "preflop":
                raw = preflop.decide(state, profiles)
            elif (
                state.get("street") == "river"
                and "call" in state["legal_actions"]
                and handeval.rank(state["board"] + state["hole_cards"]) == handeval.rank(state["board"])
                and postflop.board_unbeatable(state["board"], state["hole_cards"])
            ):
                # Equity margins must not fold an exact split pot.
                raw = {"action": "call"}
            else:
                raw = postflop_ranges_v4.decide(state, profiles)
                if (isinstance(raw, dict) and raw.get("action") == "call"
                        and "fold" in state["legal_actions"] and _hopeless_call(state)):
                    raw = {"action": "fold"}
            return common.safe_action(state, raw)
        except Exception:
            return common.safe_action(state, None)

    def on_hand_end(self, summary):
        """Forward completed hands to both opponent models."""
        try:
            self.model.observe(summary)
        except Exception:
            pass
        if self.seat is not None:
            postflop_ranges_v4.observe(summary, seat=self.seat)
