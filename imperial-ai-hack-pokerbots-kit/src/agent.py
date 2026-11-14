"""Tournament Agent entrypoint integrating opponent model and strategy modules."""

from . import common, exploits, postflop, preflop
from .opponents import OpponentModel


class Agent:
    """AlgoSoc Pokerbots Agent delegating to preflop/postflop/opponent modules."""

    def __init__(self):
        self.seat = None
        self.model = OpponentModel()

    def on_table_start(self, info):
        """Initialise per-round opponent model."""
        self.seat = info.get("seat") if isinstance(info, dict) else None
        self.model = OpponentModel()
        self.model.start(info)

    def act(self, state):
        """Route decision to preflop/postflop and enforce legal action safety."""
        try:
            profiles = self.model.profiles()
            if state.get("street") == "preflop":
                raw = preflop.decide(state, profiles)
            else:
                raw = exploits.adjust(state, profiles, postflop.decide(state, profiles))
            return common.safe_action(state, raw)
        except Exception:
            return common.safe_action(state, None)

    def on_hand_end(self, summary):
        """Forward completed hand summary to opponent model."""
        try:
            self.model.observe(summary)
        except Exception:
            pass
