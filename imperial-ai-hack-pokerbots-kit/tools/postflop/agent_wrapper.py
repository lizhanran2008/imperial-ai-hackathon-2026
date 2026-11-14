"""Joins a preflop module and a postflop module into an Agent.

Lab stand-in for the team's shared wrapper (PROJECT.md gives that to the
integration lead as build.py and src/common.py). It follows the same contract,
so a strategy that works here needs no change when the real one lands.
"""
import traceback

# Stand-in for common.DEFAULT_PROFILE: what we assume about a seat we have not
# seen play yet. Estimates, to be replaced by figures measured from real rounds.
DEFAULT_PROFILE = {
    "hands": 0,
    "vpip": 0.30,
    "pfr": 0.15,
    "three_bet": 0.05,
    "aggression": 0.40,
    "fold_to_bet": 0.45,
    "showdown": 0.30,
    "style": "unknown",
}


def safe_action(state, action):
    """Turn whatever a strategy returned into a legal action for this state."""
    legal = state["legal_actions"]
    kind = action.get("action") if isinstance(action, dict) else None
    if kind in ("raise", "all_in"):
        if "raise" in legal:
            lo, hi = state["min_raise_to"], state["max_raise_to"]
            try:
                amount = hi if kind == "all_in" else int(action.get("amount"))
            except (TypeError, ValueError, OverflowError):
                amount = lo
            return {"action": "raise", "amount": max(lo, min(hi, amount))}
        kind = "call"
    if kind == "call":
        return {"action": "call" if "call" in legal else "check"}
    # check, fold, or anything unrecognised: never fold when checking is free.
    return {"action": "check" if "check" in legal else "fold"}


def build_agent(preflop, postflop, opponents=None):
    """Return an Agent class playing `preflop.decide` before the flop and
    `postflop.decide` after it. `opponents`, if given, is a module with an
    OpponentModel class; without it every seat keeps the default profile."""

    class Agent:
        def __init__(self):
            self.model = None
            self.profiles = {}
            self.errors = 0
            self.first_error = None

        def on_table_start(self, info):
            self.profiles = {s: dict(DEFAULT_PROFILE) for s in range(info.get("num_players", 8))}
            if opponents is not None:
                try:
                    self.model = opponents.OpponentModel()
                    self.model.start(info)
                except Exception:
                    self.model = None
                    self._note_error()

        def act(self, state):
            try:
                if self.model is not None:
                    profiles = self.model.profiles()
                else:
                    if not self.profiles:
                        self.profiles = {s: dict(DEFAULT_PROFILE) for s in range(len(state["stacks"]))}
                    profiles = self.profiles
                module = preflop if state["street"] == "preflop" else postflop
                return safe_action(state, module.decide(state, profiles))
            except Exception:
                self._note_error()
                return {"action": "check" if "check" in state.get("legal_actions", ()) else "fold"}

        def on_hand_end(self, summary):
            if self.model is not None:
                try:
                    self.model.observe(summary)
                except Exception:
                    self._note_error()

        def _note_error(self):
            self.errors += 1
            if self.first_error is None:
                self.first_error = traceback.format_exc(limit=6)

    return Agent
