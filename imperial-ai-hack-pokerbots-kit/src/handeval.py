"""Hand evaluation stub (owned by Macro1027)."""

_RANK_ORDER = "23456789TJQKA"


def rank(cards):
    """Return a comparable rank tuple for 5-7 card strings (stub)."""
    ranks = sorted((_RANK_ORDER.index(c[0]) for c in cards), reverse=True)
    return (0, *ranks[:5])


def describe(hole_cards, board):
    """Return a minimal hand classification dict (stub)."""
    board_ranks = {_RANK_ORDER.index(c[0]) for c in board} if board else set()
    top_board = max(board_ranks) if board_ranks else -1
    overcards = sum(1 for c in hole_cards if _RANK_ORDER.index(c[0]) > top_board)
    return {
        "category": 0,
        "made": "high_card",
        "flush_draw": False,
        "straight_draw": "none",
        "overcards": overcards,
    }
