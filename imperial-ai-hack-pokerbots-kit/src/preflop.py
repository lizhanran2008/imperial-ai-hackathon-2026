"""Preflop strategy stub preserving starter bot behaviour (owned by cntrlaltdlt)."""

_RANK_ORDER = "23456789TJQKA"


def hand_class(hole_cards):
    """Return canonical starting hand name such as 'AKs', 'AKo', or 'TT'."""
    r0, s0 = hole_cards[0][0], hole_cards[0][1]
    r1, s1 = hole_cards[1][0], hole_cards[1][1]
    i0 = _RANK_ORDER.index(r0)
    i1 = _RANK_ORDER.index(r1)
    if i0 < i1:
        r0, r1 = r1, r0
    if r0 == r1:
        return f"{r0}{r1}"
    suffix = "s" if s0 == s1 else "o"
    return f"{r0}{r1}{suffix}"


def hand_strength(hole_cards):
    """Return a 0-1 starting hand strength estimate (stub)."""
    ranks = sorted(_RANK_ORDER.index(c[0]) for c in hole_cards)
    pair_bonus = 0.25 if ranks[0] == ranks[1] else 0.0
    suited_bonus = 0.05 if hole_cards[0][1] == hole_cards[1][1] else 0.0
    base = (ranks[0] + ranks[1]) / 24.0 * 0.7
    return min(1.0, base + pair_bonus + suited_bonus)


def decide(state, profiles):
    """Starter-equivalent preflop decision stub."""
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
