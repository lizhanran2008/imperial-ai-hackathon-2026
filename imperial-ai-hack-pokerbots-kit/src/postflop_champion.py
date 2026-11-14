"""Postflop strategy "champion": a plain made-hand ladder.

decide(state, profiles) is called when state["street"] is flop, turn or river
and returns an action dict. See PROJECT.md for the contract.

No ranges, equity or opponent reads: bet two pair or better, bet and call
cheaply with top pair, check and call very cheaply with weaker pairs, play
draws by their rough chance of completing. src/postflop.py selects which
strategy the bot plays.
"""
from . import handeval

_MONSTER = {"two_pair", "set", "trips", "straight", "flush", "full_house",
            "quads", "straight_flush"}
_GOOD = {"overpair", "top_pair"}
_WEAK = {"middle_pair", "underpair", "pair_and_board_pair"}


def _bet(state, fraction):
    """Bet or raise by `fraction` of the pot (after calling), else call/check."""
    legal = state["legal_actions"]
    if "raise" not in legal:
        return {"action": "call" if "call" in legal else "check"}
    target = max(state["bets"]) + int(fraction * (state["pot"] + state["to_call"]))
    target = max(state["min_raise_to"], min(state["max_raise_to"], target))
    return {"action": "raise", "amount": target}


def _give_up(state):
    return {"action": "check" if "check" in state["legal_actions"] else "fold"}


def decide(state, profiles):
    d = handeval.describe(state["hole_cards"], state["board"])
    made = d["made"]
    to_call = state["to_call"]
    pot = state["pot"]
    price = to_call / (pot + to_call) if to_call else 0.0
    opponents = state["folded"].count(False) - 1

    if made in _MONSTER:
        if to_call == 0 or state["raises_this_street"] < 2:
            return _bet(state, 0.75)
        return {"action": "call"}

    if made in _GOOD:
        if to_call == 0:
            return _bet(state, 0.6)
        return {"action": "call"} if price <= 0.34 else _give_up(state)

    if made in _WEAK:
        if to_call == 0:
            return {"action": "check"}
        return {"action": "call"} if price <= 0.22 else _give_up(state)

    # No made hand: play draws by their rough chance of completing.
    equity = 0.0
    if state["street"] != "river":
        per_card = 2 if state["street"] == "flop" else 1
        if d["flush_draw"]:
            equity += 0.18 * per_card
        if d["straight_draw"] == "open_ended":
            equity += 0.16 * per_card
        elif d["straight_draw"] == "gutshot":
            equity += 0.08 * per_card
    if to_call == 0:
        if equity >= 0.3 and opponents <= 2:
            return _bet(state, 0.5)
        return {"action": "check"}
    return {"action": "call"} if price < equity else _give_up(state)
