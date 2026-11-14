"""Tournament Agent entrypoint integrating opponent model and strategy modules."""

from . import common, handeval, postflop, postflop_ranges_v4, preflop
from .opponents import OpponentModel


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
