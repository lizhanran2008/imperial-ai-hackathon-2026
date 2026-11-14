"""Postflop strategy stub preserving starter bot behaviour (owned by Macro1027)."""

_RANK_ORDER = "23456789TJQKA"


def decide(state, profiles):
    """Starter-equivalent postflop decision stub."""
    legal = state["legal_actions"]
    hole = state["hole_cards"]
    ranks = sorted(_RANK_ORDER.index(c[0]) for c in hole)
    strong = ranks[0] == ranks[1] or ranks[1] >= 11  # pair or K+ high

    if strong and "raise" in legal:
        target = state["min_raise_to"] + state["pot"] // 2
        return {"action": "raise", "amount": min(target, state["max_raise_to"])}
    if "check" in legal:
        return {"action": "check"}
    if state["to_call"] <= state["big_blind"] * 2 or strong:
        return {"action": "call"}
    return {"action": "fold"}
