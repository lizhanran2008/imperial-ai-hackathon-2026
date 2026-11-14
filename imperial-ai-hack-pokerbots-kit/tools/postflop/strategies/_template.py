"""Template for a postflop candidate. Copy to strategies/<your_name>.py.

Rules for a candidate file:
  - It defines decide(state, profiles) and returns an action dict.
  - It imports only the standard library and `handeval`.
  - It is one self-contained file, because the winner is copied to
    src/postflop.py as it stands.
  - It never reads files or keeps state between hands outside module globals
    that are safe to share (precomputed tables are fine).
  - It handles state["betting"] of no_limit, pot_limit and fixed_limit; using
    min_raise_to and max_raise_to as below is enough.
  - Its tunable thresholds sit in one PARAMS dict at the top of the file, so
    the tuner can reach them.
  - Any randomness comes from a random.Random created with a fixed seed, and
    it reads the clock only for a deadline check.
  - Worst decision under 3 ms and average under 1.5 ms in `arena.py --strict`.

The target design and what the bot can see are in tools/postflop/STRATEGY.md.

Files whose name starts with "_" are skipped by the arena.

state    the dict the platform passes to act(); see the kit README.
profiles {seat: {"hands", "vpip", "pfr", "three_bet", "aggression",
         "fold_to_bet", "showdown", "style"}} for every seat at the table.
         Until the opponent model exists every seat has the default values
         and style "unknown", so a candidate must play sensibly on defaults.
"""
import handeval


def _bet(state, fraction):
    """Bet or raise by `fraction` of the pot (after calling), else call/check."""
    legal = state["legal_actions"]
    if "raise" not in legal:
        return {"action": "call" if "call" in legal else "check"}
    target = max(state["bets"]) + int(fraction * (state["pot"] + state["to_call"]))
    target = max(state["min_raise_to"], min(state["max_raise_to"], target))
    return {"action": "raise", "amount": target}


def decide(state, profiles):
    hand = handeval.describe(state["hole_cards"], state["board"])
    if hand["category"] >= 2:
        return _bet(state, 0.75)
    return {"action": "check" if "check" in state["legal_actions"] else "fold"}
