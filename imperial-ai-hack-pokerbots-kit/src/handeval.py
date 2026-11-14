"""Hand evaluation for the postflop module. Standard library only.

rank(cards)                 best 5-card hand from 5-7 card strings, as a tuple
                            that compares higher for a better hand. Identical
                            to engine/cards.py evaluate() for the same cards.
describe(hole_cards, board) what our hand is on this board, and its draws.

Cards are the platform's strings: rank then suit, e.g. "As", "Td", "2c".
"""

RANKS = "23456789TJQKA"
_R = {r: i for i, r in enumerate(RANKS)}
_S = {"c": 0, "d": 1, "h": 2, "s": 3}

CATEGORY_NAMES = ("high_card", "pair", "two_pair", "trips", "straight",
                  "flush", "full_house", "quads", "straight_flush")


def _build_straights():
    """13-bit rank mask -> highest rank index of a straight in it, or -1."""
    table = [-1] * 8192
    for mask in range(8192):
        m = (mask << 1) | (mask >> 12 & 1)  # ace also plays low
        for top in range(13, 3, -1):
            if (m >> (top - 4)) & 31 == 31:
                table[mask] = top - 1
                break
    return table


_STRAIGHT = _build_straights()


def rank(cards):
    """Score the best 5-card hand from 5-7 cards. Higher tuple wins.

    First element is the category: 0 high card, 1 pair, 2 two pair, 3 trips,
    4 straight, 5 flush, 6 full house, 7 quads, 8 straight flush.
    """
    counts = [0] * 13
    suit_mask = [0, 0, 0, 0]
    suit_n = [0, 0, 0, 0]
    mask = 0
    for c in cards:
        r = _R[c[0]]
        s = _S[c[1]]
        counts[r] += 1
        suit_mask[s] |= 1 << r
        suit_n[s] += 1
        mask |= 1 << r

    flush = None
    for s in (0, 1, 2, 3):
        if suit_n[s] >= 5:
            fm = suit_mask[s]
            sh = _STRAIGHT[fm]
            if sh >= 0:
                return (8, sh)
            flush = tuple([r for r in range(12, -1, -1) if fm >> r & 1][:5])
            break

    quads = -1
    trips = []
    pairs = []
    singles = []
    for r in range(12, -1, -1):
        n = counts[r]
        if n == 1:
            singles.append(r)
        elif n == 2:
            pairs.append(r)
        elif n == 3:
            trips.append(r)
        elif n == 4:
            quads = r

    if quads >= 0:
        for r in range(12, -1, -1):
            if counts[r] and r != quads:
                return (7, quads, r)
    if trips and (len(trips) > 1 or pairs):
        return (6, trips[0], trips[1] if len(trips) > 1 else pairs[0])
    if flush:
        return (5,) + flush
    sh = _STRAIGHT[mask]
    if sh >= 0:
        return (4, sh)
    if trips:
        return (3, trips[0]) + tuple(singles[:2])
    if len(pairs) >= 2:
        p0, p1 = pairs[0], pairs[1]
        for r in range(12, -1, -1):
            if counts[r] and r != p0 and r != p1:
                return (2, p0, p1, r)
    if pairs:
        return (1, pairs[0]) + tuple(singles[:3])
    return (0,) + tuple(singles[:5])


def describe(hole_cards, board):
    """Classify our hand on this board.

    Returns a dict with:
      category       int 0-8, as in rank()
      made           "high_card", "board_pair", "bottom_pair", "middle_pair",
                     "top_pair", "underpair", "overpair", "board_two_pair",
                     "pair_and_board_pair", "two_pair", "board_trips", "trips",
                     "set", "straight", "flush", "full_house", "quads",
                     "straight_flush", or "board" when the five board cards
                     alone are our best hand. Before the flop: "pocket_pair"
                     or "high_card".
      flush_draw     bool: four to a flush using at least one hole card
      straight_draw  "none", "gutshot" (one rank completes it) or "open_ended"
                     (two or more ranks complete it). A rank that would give
                     the board alone the same straight does not count.
      overcards      int: hole cards ranked above every board card
    """
    h0, h1 = _R[hole_cards[0][0]], _R[hole_cards[1][0]]
    if len(board) < 3:
        pair = h0 == h1
        return {"category": 1 if pair else 0, "made": "pocket_pair" if pair else "high_card",
                "flush_draw": False, "straight_draw": "none", "overcards": 0}

    full = rank(hole_cards + board)
    cat = full[0]
    bc = [0] * 13
    board_mask = 0
    for c in board:
        r = _R[c[0]]
        bc[r] += 1
        board_mask |= 1 << r
    top_board = board_mask.bit_length() - 1

    if len(board) == 5 and rank(board) == full:
        made = "board"
    elif cat == 0:
        made = "high_card"
    elif cat == 1:
        p = full[1]
        if bc[p] == 2:
            made = "board_pair"
        elif h0 == h1:
            made = "overpair" if p > top_board else "underpair"
        elif p == top_board:
            made = "top_pair"
        elif board_mask & ((1 << p) - 1) == 0:
            made = "bottom_pair"
        else:
            made = "middle_pair"
    elif cat == 2:
        ours = 0
        for p in (full[1], full[2]):
            if bc[p] < 2 and (h0 == p or h1 == p):
                ours += 1
        made = ("board_two_pair", "pair_and_board_pair", "two_pair")[ours]
    elif cat == 3:
        made = ("set", "set", "trips", "board_trips")[bc[full[1]]]
    else:
        made = CATEGORY_NAMES[cat]

    flush_draw = False
    straight_draw = "none"
    if len(board) < 5:
        if cat != 5 and cat != 8:
            for hc in hole_cards:
                s = hc[1]
                n = (hole_cards[0][1] == s) + (hole_cards[1][1] == s)
                for c in board:
                    n += c[1] == s
                if n == 4:
                    flush_draw = True
                    break
        mask = board_mask | 1 << h0 | 1 << h1
        if _STRAIGHT[mask] < 0:
            outs = 0
            for r in range(13):
                bit = 1 << r
                # Counts only if the card gives us a better straight than it
                # gives the board on its own (-1 means no straight).
                if not mask & bit and _STRAIGHT[mask | bit] > _STRAIGHT[board_mask | bit]:
                    outs += 1
            if outs >= 2:
                straight_draw = "open_ended"
            elif outs == 1:
                straight_draw = "gutshot"

    return {"category": cat, "made": made, "flush_draw": flush_draw,
            "straight_draw": straight_draw,
            "overcards": (h0 > top_board) + (h1 > top_board)}
