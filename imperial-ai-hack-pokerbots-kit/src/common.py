"""Shared constants, position helpers, and action validation."""

VALID_STYLES = (
    "unknown",
    "tight_passive",
    "tight_aggressive",
    "loose_passive",
    "loose_aggressive",
    "maniac",
)

DEFAULT_PROFILE = {
    "hands": 0,
    "vpip": 0.25,
    "pfr": 0.15,
    "three_bet": 0.06,
    "aggression": 0.40,
    "fold_to_bet": 0.50,
    "showdown": 0.30,
    "style": "unknown",
}


def position(state):
    """Return active seats after the button (0 for the button itself)."""
    folded = state["folded"]
    seat = state["seat"]
    button = state["button"]
    n = len(folded)
    if seat == button:
        return 0
    count = 0 if folded[button] else 1
    for step in range(1, n + 1):
        idx = (button + step) % n
        if idx == seat:
            return count
        if not folded[idx]:
            count += 1
    return 0


def _fallback_action(legal, to_call):
    if to_call == 0 and "check" in legal:
        return {"action": "check"}
    if "fold" in legal:
        return {"action": "fold"}
    if "check" in legal:
        return {"action": "check"}
    if "call" in legal:
        return {"action": "call"}
    return {"action": "fold"}


def safe_action(state, action):
    """Coerce an action dict into a legal action for the current state."""
    legal = state.get("legal_actions") or []
    to_call = state.get("to_call", 0)
    min_raise = state.get("min_raise_to")
    max_raise = state.get("max_raise_to")

    if not isinstance(action, dict):
        return _fallback_action(legal, to_call)

    kind = action.get("action")

    if kind == "all_in":
        if "raise" in legal and max_raise is not None:
            return {"action": "all_in"}
        if to_call == 0 and "check" in legal:
            return {"action": "check"}
        if "call" in legal:
            return {"action": "call"}
        return _fallback_action(legal, to_call)

    if kind == "raise":
        if "raise" in legal and min_raise is not None and max_raise is not None:
            raw_amount = action.get("amount", min_raise)
            try:
                amount = int(raw_amount)
            except (TypeError, ValueError, OverflowError):
                amount = int(min_raise)
            clamped = max(int(min_raise), min(int(max_raise), amount))
            return {"action": "raise", "amount": clamped}
        if to_call == 0 and "check" in legal:
            return {"action": "check"}
        if "call" in legal:
            return {"action": "call"}
        return _fallback_action(legal, to_call)

    if kind == "call":
        if to_call == 0 and "check" in legal:
            return {"action": "check"}
        if "call" in legal:
            return {"action": "call"}
        return _fallback_action(legal, to_call)

    if kind == "check":
        if to_call == 0 and "check" in legal:
            return {"action": "check"}
        return _fallback_action(legal, to_call)

    if kind == "fold":
        if "fold" in legal:
            return {"action": "fold"}
        return _fallback_action(legal, to_call)

    return _fallback_action(legal, to_call)
