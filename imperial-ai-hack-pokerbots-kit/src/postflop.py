"""Postflop strategy (owned by Macro1027): a plain made-hand ladder.

decide(state, profiles) is called when state["street"] is flop, turn or river
and returns an action dict. See PROJECT.md for the contract.

No ranges, equity or opponent reads: bet two pair or better, bet and call
cheaply with top pair, check and call very cheaply with weaker pairs, play
draws by their rough chance of completing. When the five board cards are our
hand and nothing an opponent can hold beats them, the pot is a guaranteed
split, so never fold.
"""
from . import handeval

_RANKS = "23456789TJQKA"
_DECK = [r + s for r in _RANKS for s in "cdhs"]

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


_unbeatable = {}


def board_unbeatable(board, hole_cards):
    """True when no two cards an opponent could hold beat the five board cards.

    Our own hole cards are out of the deck. One card that improves the board
    settles it. A hand that needs both cards to beat a board no single card
    beats is either two cards of a suit the board has three or more of (flush
    or straight flush) or a pocket pair (quads over a full house), so only
    those pairs are tried. The answer is kept for the rest of the hand.
    """
    key = tuple(board) + tuple(hole_cards)
    known = _unbeatable.get(key)
    if known is None:
        rank = handeval.rank
        board = list(board)
        base = rank(board)
        deck = [c for c in _DECK if c not in key]
        known = not any(rank(board + [c]) > base for c in deck)
        if known:
            suits = [c[1] for c in board]
            for i, c in enumerate(deck):
                for e in deck[i + 1:]:
                    if (c[0] == e[0] or (c[1] == e[1] and suits.count(c[1]) >= 3)) \
                            and rank(board + [c, e]) > base:
                        known = False
                        break
                if not known:
                    break
        if len(_unbeatable) > 64:
            _unbeatable.clear()
        _unbeatable[key] = known
    return known


def decide(state, profiles):
    d = handeval.describe(state["hole_cards"], state["board"])
    made = d["made"]
    to_call = state["to_call"]
    pot = state["pot"]
    price = to_call / (pot + to_call) if to_call else 0.0
    opponents = state["folded"].count(False) - 1

    if made == "board" and board_unbeatable(state["board"], state["hole_cards"]):
        # Guaranteed split: calling costs nothing in the long run, folding gives up our share.
        return {"action": "call" if "call" in state["legal_actions"] else "check"}

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
