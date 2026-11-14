"""Postflop strategy "ranges_v4": ranges_v3 made harder to play against.

Experimental: not imported by src/postflop.py and not bundled by build.py.

The model and the machinery are ranges_v3's (board table -> opponent ranges ->
stratified trials -> one EV table -> fallback). v3 was only ever measured
against bots that never fold or act at random. These changes are aimed at
opponents that fold, bluff and adapt:

  1 Bluffs in every bet size. v3 bluffed only heads-up, only after seeing an
    opponent face eight bets, and only when the estimate said it clearly won
    chips, so its bets were almost always strong hands and the bigger the bet
    the stronger the hand. v4 also bets a set share of its draws and its
    worthless hands (bluff_freq), against one or two opponents, whenever the
    estimate says betting is no worse than checking by more than bluff_floor.
    Those bets take their size from a fixed mix (bluff_size_mix), and value
    bets sometimes take a second-best size (size_jitter), so no size is all
    strong hands. A seat that does not fold makes the estimate fail the
    floor, which stops the bluffs against it.
  2 Learning from the end of every hand. observe(summary) counts the actions
    this module never saw (everything after our last decision, and every hand
    we folded before the flop), and for each opponent hand shown at showdown
    records whether each bet it made was a bluff (seff under bluff_seff on
    that street). An opponent's bluff share then comes from its own
    showdowns, shrunk toward the prior. observe() is only called if the Agent
    forwards on_hand_end to it; without that call v4 learns as v3 did.
  3 Calling lighter against seats that bet a lot. The safety margins on a
    call are scaled down as the bettor's share of bets-when-checked-to rises
    from aggro_lo to aggro_hi (use_aggro_margin). The margin for players
    still to act behind us is not scaled. The guard against being run over
    now triggers after 6 heads-up bets from a seat with 60% folded, not 12
    with 70%.

Everything else, including the accuracy trades described in ranges_v3, is
unchanged. Every number above is a first guess.
"""
import random
import time
from bisect import bisect_left, bisect_right
from collections import Counter, deque
from itertools import accumulate, chain
from operator import add, itemgetter, mul

PARAMS = {
    # time
    "deadline_ms": 3.0,            # trials stop this long after decide() starts
    "update_ms": 1.4,              # after this, range updates for checks are skipped
    # Trials by street (flop, turn, river). Fewer than v2's 200 because v3's
    # estimates are less noisy per trial: see the module docstring.
    "trials_hu": (150, 100, 100), "trials_multi": (150, 120, 150),
    "min_share": 0.6,              # below this share of the planned trials, fall back
    "opp_samples": 600,            # trials x opponents is held at or under this; None = no cap
    "bands": ((0.00, 0.30, 28), (0.30, 0.55, 28), (0.55, 0.75, 32),
              (0.75, 0.88, 36), (0.88, 0.96, 40), (0.96, 1.00, 36)),
    "top": 0.88,                   # "strong" means ahead of the top 12% of the main opponent
    # draw floors on seff: (flop, turn)
    "floor_combo": (0.80, 0.65), "floor_draw": (0.62, 0.50), "floor_gutshot": (0.35, 0.25),
    # preflop seeding
    "seat_mult": (0.55, 0.65, 0.75, 0.90, 1.20, 1.70, 1.50),   # first seat to small blind, 8 seats
    "open_min": 0.03, "open_max": 0.70,
    # likelihoods
    "value_bets": 0.85,            # share of top-of-range hands that bet (the rest slow-play)
    "bluff": (0.30, 0.25, 0.20, 0.12),          # bluff share by size bucket
    "size_edges": (0.45, 0.85, 1.60),           # bet as a share of the pot: bucket upper edges
    "call_raise_like": 0.30, "call_below_like": 0.05,
    # priors for opponent stats
    "prior": {"stab": 0.35, "cont": (0.70, 0.55, 0.42, 0.30), "cont_raise": 0.35, "raise": 0.08,
              "pfr": 0.15, "vpip": 0.30, "three_bet": 0.05},
    "prior_weight_pre": 20.0, "prior_weight_post": 10.0,
    # not facing a bet
    "sizes": (0.33, 0.66, 1.0), "allin_spr": 1.5,
    "stab_size": 0.66,
    "realize_last": 0.97, "realize_not_last": 0.92,
    "value_gain": 0.02,            # of the pot, per opponent
    "bluff_gain": 0.10, "bluff_full": 0.30, "bluff_max_freq": 0.7, "bluff_min_seen": 8,
    # Bluffs mixed into the betting range at set frequencies: (one opponent, two opponents).
    # cbet: worthless hand on the flop after we made the last raise before it; barrel: the same
    # on a later street; probe: worthless hand without the lead; draw: flush draw or open-ender.
    "bluff_freq": {"cbet": (0.50, 0.20), "barrel": (0.35, 0.12), "probe": (0.20, 0.0), "draw": (0.70, 0.40)},
    "bluff_opps_max": 2,           # never into more opponents than this
    "bluff_air": 0.40,             # a hand under this seff with no draw is worthless
    "bluff_floor": -0.03,          # a mixed-in bluff may be this share of the pot worse than checking, by our estimate
    "bluff_size_mix": (0.45, 0.40, 0.15),   # share of mixed-in bluffs at each of `sizes`
    "size_jitter": 0.25, "size_jitter_tol": 0.05,   # value bets: how often, and how far below the best size's EV (share of pot)
    # Showdowns: a shown bet was a bluff if the hand's seff on that street was under bluff_seff.
    "bluff_seff": 0.35, "prior_weight_bluff": 6.0,
    "commit_frac": 0.5,
    # facing a bet
    "margin_street": 0.015, "margin_oop": 0.02, "margin_behind": 0.025, "margin_stack": 0.04,
    "raise_mult": 3.0, "raise_eq": 0.65, "raise_gain": 0.03, "draw_raise_gain": 0.10,
    "runover_min": 6, "runover_share": 0.60,
    # Scale the call margins down as the bettor's bet-when-checked-to share goes from aggro_lo to aggro_hi.
    "use_aggro_margin": True, "aggro_lo": 0.40, "aggro_hi": 0.65,
    "dead_window": 40, "dead_facing": 10,
    # switches for the calibration changes
    "use_size_buckets": True, "use_seat_width": True, "use_raise_risk": True,
    "use_runover_guard": True, "use_dead_bot": True, "use_bluffs": True,
    # Skip the calculation for a hand with seff under shortcut_seff against two
    # or more opponents: check, or fold to a bet of at least shortcut_price of
    # the pot after calling.
    "use_shortcut": True, "shortcut_seff": 0.30, "shortcut_price": 0.12,
    # set True to let exceptions out (tests and CI); normally they become the fallback action
    "raise_errors": False,
}

# Counters for the promotion gate. Read them after a run; nothing resets them.
STATS = {"decisions": 0, "fallback_trials": 0, "fallback_error": 0, "fallback_no_table": 0,
         "exceptions": {}, "trials": 0, "skipped_updates": 0, "slowest_ms": 0.0, "shortcuts": 0,
         "mixed_bluffs": 0, "observed_hands": 0, "shown_bets": 0, "shown_bluffs": 0, "observe_errors": 0}

_RNG = random.Random(20261114)
_CLOCK = time.perf_counter
_BOARD_LEN = {"flop": 3, "turn": 4, "river": 5}
_STREETS_LEFT = {"flop": 2, "turn": 1, "river": 0}
# Fallback: rows by hero's seff (air, weak pair, top pair, two pair or better);
# columns are no bet / small / medium / big bet. b bet, r raise, c call, x check or fold.
_FALLBACK = ("xxxx", "xcxx", "bccx", "brrc")
_FALLBACK_ROWS = (0.45, 0.70, 0.90)


# --------------------------------------------------------------------------
# Cards, combinations and a table-based evaluator
# --------------------------------------------------------------------------

_ID = {r + s: i * 4 + j for i, r in enumerate("23456789TJQKA") for j, s in enumerate("cdhs")}
_K5 = [5 ** (c >> 2) for c in range(52)]     # sum over cards = the rank counts, base 5
_S8 = [8 ** (c & 3) for c in range(52)]      # sum over cards = the suit counts, base 8
_P13 = (28561, 2197, 169, 13, 1)


def _build_straights():
    """13-bit rank mask -> top rank of a straight in it (or -1), and how many
    ranks would complete one when there is none."""
    top = [-1] * 8192
    for mask in range(8192):
        m = (mask << 1) | (mask >> 12 & 1)
        for hi in range(13, 3, -1):
            if (m >> (hi - 4)) & 31 == 31:
                top[mask] = hi - 1
                break
    outs = bytearray(8192)
    for mask in range(8192):
        if top[mask] < 0:
            outs[mask] = sum(1 for r in range(13) if not mask >> r & 1 and top[mask | 1 << r] >= 0)
    return top, outs


_STOP, _OUTS = _build_straights()


def _pack(cat, ranks):
    v = 0
    for k, r in enumerate(ranks):
        v += r * _P13[k]
    return cat << 20 | v


def _nf_value(counts):
    """Value of the best five cards ignoring flushes, from 13 rank counts."""
    quads = -1
    trips, pairs, singles = [], [], []
    mask = 0
    for r in range(12, -1, -1):
        n = counts[r]
        if n:
            mask |= 1 << r
            if n == 1:
                singles.append(r)
            elif n == 2:
                pairs.append(r)
            elif n == 3:
                trips.append(r)
            else:
                quads = r
    if quads >= 0:
        return _pack(7, (quads, max(r for r in range(13) if counts[r] and r != quads)))
    if trips and (len(trips) > 1 or pairs):
        return _pack(6, (trips[0], trips[1] if len(trips) > 1 else pairs[0]))
    if _STOP[mask] >= 0:
        return _pack(4, (_STOP[mask],))
    if trips:
        return _pack(3, [trips[0]] + singles[:2])
    if len(pairs) >= 2:
        rest = max(r for r in range(13) if counts[r] and r != pairs[0] and r != pairs[1])
        return _pack(2, (pairs[0], pairs[1], rest))
    if pairs:
        return _pack(1, [pairs[0]] + singles[:3])
    return _pack(0, singles[:5])


def _build_tables():
    """_NF: base-5 rank-count key -> value, for every 5, 6 and 7 card rank
    multiset. _FV: flush-suit rank mask -> value. _FLUSH: base-8 suit-count
    key -> the suit with five or more cards, or -1."""
    nf = {}
    counts = [0] * 13

    def walk(r, used, key):
        if r == 13:
            if used >= 5:
                nf[key] = _nf_value(counts)
            return
        if used + 4 * (13 - r) < 5:
            return
        p = 5 ** r
        for n in range(min(4, 7 - used) + 1):
            counts[r] = n
            walk(r + 1, used + n, key + n * p)
        counts[r] = 0

    walk(0, 0, 0)
    fv = [0] * 8192
    for mask in range(8192):
        ranks = [r for r in range(12, -1, -1) if mask >> r & 1]
        if len(ranks) >= 5:
            fv[mask] = _pack(8, (_STOP[mask],)) if _STOP[mask] >= 0 else _pack(5, ranks[:5])
    flush = [-1] * 4096
    for key in range(4096):
        for s in range(4):
            n = key >> (3 * s) & 7
            if n >= 5:
                flush[key] = s
    return nf, fv, flush


_NF, _FV, _FLUSH = _build_tables()
# Suit-count key of five board cards -> can anyone make a flush on it.
_FLUSH3 = [any((key >> (3 * s) & 7) >= 3 for s in range(4)) for key in range(4096)]

_C1, _C2 = [], []
for _a in range(52):
    for _b in range(_a + 1, 52):
        _C1.append(_a)
        _C2.append(_b)
_NC = len(_C1)                                           # 1326
_CIDX = {(_C1[i], _C2[i]): i for i in range(_NC)}
_WITH = [[i for i in range(_NC) if _C1[i] == c or _C2[i] == c] for c in range(52)]
_CK = [_K5[_C1[i]] + _K5[_C2[i]] for i in range(_NC)]
_CS = [_S8[_C1[i]] + _S8[_C2[i]] for i in range(_NC)]
_CBIT = [1 << _C1[i] | 1 << _C2[i] for i in range(_NC)]              # the two cards as bits
_ALL = list(range(_NC))
# By rank pair (low rank * 13 + high rank): the two ranks' share of the base-5 key.
_RPS = [a * 13 + b for a in range(13) for b in range(a, 13)]
_RPK = {rp: 5 ** (rp // 13) + 5 ** (rp % 13) for rp in _RPS}
_CRP = [(_C1[i] >> 2) * 13 + (_C2[i] >> 2) for i in range(_NC)]    # rank pair, low rank first
_RPAB = {rp: divmod(rp, 13) for rp in _RPS}
# By suit pair (first card's suit * 4 + second card's suit): the combinations that have it.
_SPM = [[i for i in range(_NC) if (_C1[i] & 3) * 4 + (_C2[i] & 3) == sp] for sp in range(16)]
# The combinations of each rank pair; the same without the one suited in a given suit; one-hand lists.
_RPM = {rp: [i for i in range(_NC) if _CRP[i] == rp] for rp in _RPS}
_RPMX = [{rp: [i for i in _RPM[rp] if i not in set(_SPM[s * 5])] for rp in _RPS} for s in range(4)]
_ONE = [[i] for i in range(_NC)]
_FIRST = itemgetter(0)
_SECOND = itemgetter(1)


def _value(cards):
    """Value of the best five of 5-7 card ids. Higher wins. Not used when
    playing (the hot loops read the tables directly); kept for checks."""
    k = s = 0
    for c in cards:
        k += _K5[c]
        s += _S8[c]
    f = _FLUSH[s]
    v = _NF[k]
    if f >= 0:
        m = 0
        for c in cards:
            if c & 3 == f:
                m |= 1 << (c >> 2)
        if _FV[m] > v:
            v = _FV[m]
    return v


def _build_order():
    """Combination indices, strongest preflop hands first (v1 ranking)."""
    scored = []
    for i in range(_NC):
        hi, lo = _C2[i] >> 2, _C1[i] >> 2
        if hi == lo:
            score = 14 + 2.2 * hi
        else:
            gap = hi - lo
            score = 1.6 * hi + 0.9 * lo + (3 if (_C1[i] ^ _C2[i]) & 3 == 0 else 0) + max(0, 3 - gap)
        scored.append((-score, i))
    scored.sort()
    return [i for _, i in scored]


_ORDER = _build_order()
_pools = {}


def _pool(cls, width, vpip, three_bet):
    """Preflop weights (list of 1326) for an action class. `width` is the
    opening width for "open"; the others use vpip and three_bet."""
    key = (cls, int(width * 40 + 0.5), int(vpip * 20 + 0.5), int(three_bet * 40 + 0.5))
    pool = _pools.get(key)
    if pool is None:
        p, v, t = key[1] / 40.0, min(0.9, max(0.15, key[2] / 20.0)), min(0.3, max(0.03, key[3] / 40.0))
        if cls == "3bet":
            segs = ((0, t, 1.0), (t, 2.5 * t, 0.35))
        elif cls == "open":
            segs = ((0, p, 1.0), (p, 1.6 * p, 0.4))
        elif cls == "call":
            segs = ((0, 0.04, 0.4), (0.04, v, 1.0), (v, 1.5 * v, 0.35))
        elif cls == "limp":
            segs = ((0, 0.08, 0.3), (0.08, max(v, 0.4), 1.0), (max(v, 0.4), 1.0, 0.3))
        else:  # checked the big blind, or never acted: nearly any two cards
            segs = ((0, 0.08, 0.3), (0.08, 1.0, 1.0))
        pool = [0.0] * _NC
        for lo, hi, w in segs:
            for i in _ORDER[int(lo * _NC):max(int(lo * _NC) + 1, int(min(hi, 1.0) * _NC))]:
                pool[i] = w
        _pools[key] = pool
    return pool


def _speed_scale():
    """Time a fixed loop at import; below 1.0 when this machine is slower than
    the one the trial counts were set on. Clamped, because one sample is noisy."""
    best = 1e9
    for _ in range(3):
        t = _CLOCK()
        x = 0
        nf = _NF
        for i in range(2000):
            x += nf[_CK[i % _NC] + 31]       # 31 = ranks 2, 3 and 4 once each
        best = min(best, _CLOCK() - t)
    return min(1.0, max(0.6, 0.00045 / max(best, 1e-9)))


for _cls in ("3bet", "open", "call", "limp", "check"):
    _pool(_cls, 0.15, 0.30, 0.05)
_SCALE = _speed_scale()


# --------------------------------------------------------------------------
# 1. Board table
# --------------------------------------------------------------------------

class _Street:
    """One board. order = all 1326 combinations, weakest first (hands that
    use a board card stay in it, with zero weight in every range); opad =
    order with one spare entry for sampling; pick re-orders a by-combination
    list into this order. A hand's seff is seff[i] when that list exists,
    else xs[i] if it is listed there, else srp[its rank pair]."""
    __slots__ = ("ids", "n", "order", "opad", "pick", "seff", "srp", "xs")


def _seff(st, i):
    if st.seff is not None:
        return st.seff[i]
    if st.xs is not None:
        x = st.xs.get(i)
        if x is not None:
            return x
    return st.srp[_CRP[i]]


def _street(ids):
    """Strength of every two-card hand on this board.

    Without a flush, a hand's value depends only on its two ranks, so values,
    shares and draw floors are worked out for the 91 rank pairs. On most
    boards the order is then just the rank pairs sorted, with their hands
    written out; the only hands placed one by one are flush draws in the one
    suit the board has two of. Boards with three of a suit, or two suits with
    two each before the river, take the slower route of sorting every hand."""
    p = PARAMS
    nb = len(ids)
    bk = bmask = bbits = 0
    bsuit = [0, 0, 0, 0]
    bsm = [0, 0, 0, 0]
    lv = [4] * 13
    for c in ids:
        bk += _K5[c]
        bmask |= 1 << (c >> 2)
        bbits |= 1 << c
        bsuit[c & 3] += 1
        bsm[c & 3] |= 1 << (c >> 2)
        lv[c >> 2] -= 1
    get = _NF.get
    rv = [None] * 169
    count = {}
    for rp, k in _RPK.items():
        v = rv[rp] = get(bk + k)
        if v is not None:
            a, b = _RPAB[rp]
            k = lv[a] * lv[b] if a != b else lv[a] * (lv[a] - 1) // 2
            if k:
                count[v] = count.get(v, 0) + k
    top = max(bsuit)
    flushed = None
    if top >= 3:
        # A flush is possible: find the live hands that have one and recount them.
        fv, c1s, c2s, crp, cbit = _FV, _C1, _C2, _CRP, _CBIT
        f = bsuit.index(top)
        lack = 5 - top
        if lack == 2:
            members = _SPM[f * 5]
        elif lack == 1:
            members = [i for sp in range(16) if sp // 4 == f or sp % 4 == f for i in _SPM[sp]]
        else:
            members = _ALL
        base = bsm[f]
        flushed = {}
        for i in members:
            if bbits & cbit[i]:
                continue
            c1 = c1s[i]
            c2 = c2s[i]
            m = base
            if c1 & 3 == f:
                m |= 1 << (c1 >> 2)
            if c2 & 3 == f:
                m |= 1 << (c2 >> 2)
            v = rv[crp[i]]
            if fv[m] > v:
                flushed[i] = fv[m]
                count[v] -= 1
                count[fv[m]] = count.get(fv[m], 0) + 1
    n = (52 - nb) * (51 - nb) // 2
    share = {}
    scale = 1.0 / (n - 1)
    below = 0
    for v in sorted(count):
        k = count[v]
        if k:
            share[v] = (below + 0.5 * (k - 1)) * scale
            below += k
    sget = share.get
    srp = [0.0] * 169
    sd = None
    if nb == 5:
        for rp in _RPS:
            srp[rp] = sget(rv[rp], 0.0)
        twos = []
    else:
        col = 0 if nb == 3 else 1
        f_none = (0.0, p["floor_gutshot"][col], p["floor_draw"][col])       # by straight outs 0, 1, 2+
        f_flush = (p["floor_draw"][col], p["floor_combo"][col], p["floor_combo"][col])
        # Straight outs by rank pair: 0, 1 (gutshot) or 2 (open-ended); 0 once a straight is made.
        stop, outs = _STOP, _OUTS
        sd = [0] * 169
        for rp in _RPS:
            a, b = _RPAB[rp]
            m = bmask | 1 << a | 1 << b
            o = 0
            if stop[m] < 0:
                o = outs[m]
                if o > 2:
                    o = 2
                sd[rp] = o
            x = sget(rv[rp], 0.0)
            fl = f_none[o]
            srp[rp] = fl if fl > x else x
        twos = [s for s in range(4) if bsuit[s] == 2]

    st = _Street()
    st.ids = ids
    st.n = n
    st.srp = srp
    st.seff = st.xs = None
    if top <= 2 and len(twos) <= 1:
        # Quick route: whole rank pairs in order, plus the flush draws one by one.
        items = None
        if twos:
            s2 = twos[0]
            lists = _RPMX[s2]
            crp = _CRP
            st.xs = xs = {}
            items = []
            for i in _SPM[s2 * 5]:
                rp = crp[i]
                x = srp[rp]
                fl = f_flush[sd[rp]]
                if fl > x:
                    x = fl
                xs[i] = x
                items.append((x, _ONE[i]))
            items += [(srp[rp], lists[rp]) for rp in _RPS]
        else:
            lists = _RPM
            items = [(srp[rp], lists[rp]) for rp in _RPS]
        items.sort(key=_FIRST)
        order = list(chain.from_iterable(map(_SECOND, items)))
    else:
        seff = list(map(srp.__getitem__, _CRP))
        if flushed:
            for i, v in flushed.items():
                seff[i] = share[v]
        if nb < 5:
            # A flush draw needs four of a suit with a hole card among them.
            crp = _CRP
            for sp in range(16):
                s1 = sp >> 2
                s2 = sp & 3
                for s3 in ((s1,) if s1 == s2 else (s1, s2)):
                    if bsuit[s3] < 4 and bsuit[s3] + (s1 == s3) + (s2 == s3) == 4:
                        for i in _SPM[sp]:
                            fl = f_flush[sd[crp[i]]]
                            if fl > seff[i]:
                                seff[i] = fl
                        break
        st.seff = seff
        order = sorted(_ALL, key=seff.__getitem__)
    st.order = order
    st.opad = order + [order[-1]]
    st.pick = itemgetter(*order)
    return st


# --------------------------------------------------------------------------
# 2. Opponent ranges
# --------------------------------------------------------------------------

class _Range:
    """An opponent's weights, held twice: `wc` by combination, and `w` in the
    current street's strength order, weakest first, so that a hand's place on
    the cumulative-weight axis is its percentile within this opponent's own
    range. Updates are worked out on `w` and copied back to `wc` for the hands
    that changed; entering a street re-orders `wc` in one step."""
    __slots__ = ("wc", "w", "order", "street", "cum", "total", "zeroed")

    def __init__(self, weights):
        self.wc = weights
        self.zeroed = 0              # board cards whose hands have been given zero weight
        self.w = None
        self.order = None
        self.street = None
        self.cum = None
        self.total = 0.0

    def enter(self, name, st):
        wc = self.wc
        ids = st.ids
        for c in ids[self.zeroed:]:
            for i in _WITH[c]:
                wc[i] = 0.0
        self.zeroed = len(ids)
        self.w = list(st.pick(wc))
        self.order = st.order
        self.street = name
        self.cum = None

    def ready(self):
        if self.cum is None:
            self.cum = cum = list(accumulate(self.w))
            self.total = cum[-1]

    def apply(self, t1, l0, l1, t2=2.0, l2=0.0):
        """Multiply each hand's weight by the likelihood of an action: l0 below
        percentile t1, l1 from t1 to t2, l2 above t2. A hand belongs to the
        piece its midpoint on the cumulative-weight axis falls in.

        Only relative weights matter, so the piece below t1 or the piece above
        it, whichever is longer, is left as it is and the rest is scaled
        against it. When the lower piece is the one left alone, its cumulative
        sums are kept too."""
        if self.cum is None:
            self.ready()
        total = self.total
        if total <= 0.0 or l0 <= 0.0 or l1 <= 0.0:
            return
        w = self.w
        cum = self.cum
        n = len(w)
        a = t1 * total
        pa = bisect_right(cum, a)
        if pa < n and cum[pa] - 0.5 * w[pa] < a:
            pa += 1
        if t2 < 1.0:
            b = t2 * total
            pb = bisect_right(cum, b)
            if pb < n and cum[pb] - 0.5 * w[pb] < b:
                pb += 1
            if pb < pa:
                pb = pa
        else:
            pb = n
        if pa * 2 >= n:
            # Leave the lower piece; scale the middle and top against it.
            k1 = l1 / l0
            up = [x * k1 for x in w[pa:pb]]
            if pb < n:
                k2 = l2 / l0
                up += [x * k2 for x in w[pb:]]
            cup = list(accumulate(up, initial=cum[pa - 1] if pa else 0.0))
            if cup[-1] <= 0.0:      # the action was impossible under the model: keep the old range
                return
            del cup[0]
            _scatter(self.wc, self.order[pa:], up)
            w[pa:] = up
            cum[pa:] = cup
            if cup:
                self.total = cup[-1]
            return
        # Leave the middle piece; scale the lower and top against it.
        k0 = l0 / l1
        low = [x * k0 for x in w[:pa]]
        top = None
        if pb < n:
            k2 = l2 / l1
            top = [x * k2 for x in w[pb:]]
        if sum(low) + sum(w[pa:pb]) + (sum(top) if top else 0.0) <= 0.0:
            return
        _scatter(self.wc, self.order, low)
        w[:pa] = low
        if top:
            _scatter(self.wc, self.order[pb:], top)
            w[pb:] = top
        self.cum = cum = list(accumulate(w))
        self.total = cum[-1]


def _scatter(target, places, values):
    """target[place] = value for each pair, without a Python-level loop."""
    deque(map(target.__setitem__, places, values), maxlen=0)


def _aggr(freq, bluff_share):
    """Likelihood pieces for a bet or raise by a seat that takes it `freq` of
    the time. Value bets are freq * (1 - bluff_share) of the range, from the
    top, where hands bet value_bets of the time; everything below bets at a
    flat rate so that the average is freq. Returns (threshold, below, above)."""
    hi = PARAMS["value_bets"]
    freq = min(0.98, max(0.01, freq))
    top = min(0.999, freq * (1.0 - bluff_share) / hi)
    below = (freq - hi * top) / (1.0 - top)
    # A seat that bets more often than value_bets would need a rate above 1 here: cap it.
    return 1.0 - top, min(0.98, max(below, 0.002)), hi


# --------------------------------------------------------------------------
# 7. Opponent stats, counted from the histories we are shown
# --------------------------------------------------------------------------

class _Seat:
    __slots__ = ("stab", "cont", "raise_", "recent", "hu", "bl")

    def __init__(self):
        self.stab = [0, 0]                       # [bets, chances] when checked to
        self.cont = [[0, 0], [0, 0], [0, 0], [0, 0]]   # [continued, faced] by size bucket
        self.raise_ = [0, 0]                     # [raised, faced a bet]
        self.recent = deque(maxlen=PARAMS["dead_window"])   # (passive, facing a bet)
        self.hu = deque(maxlen=24)               # did we fold to their heads-up bet
        self.bl = [[0, 0], [0, 0], [0, 0], [0, 0]]     # [bluffs, bets shown at showdown] by size bucket


class _Table:
    """Everything remembered for one of our seats during a round."""

    def __init__(self, n):
        self.n = n
        self.seat = None             # our own seat
        self.seats = [_Seat() for _ in range(n)]
        # Table-wide totals of the per-seat counts, kept running.
        self.all_stab = [0, 0]
        self.all_cont = [[0, 0], [0, 0], [0, 0], [0, 0]]
        self.all_raise = [0, 0]
        self.hand = None
        self.reset_hand()

    def reset_hand(self):
        self.done = 0                # history entries already processed
        self.profs = None            # shrunk profiles, read once per hand
        self.pending = []            # range updates queued by _advance: (seat, street, is a check, likelihood)
        self.pre = {}                # seat -> preflop action class
        self.pre_raises = 0
        self.blinds = [None, None]
        self.ranges = None           # seat -> _Range, once the flop is out
        self.streets = {}            # street name -> _Street
        self.pot = 0
        self.bets = {}
        self.street = "preflop"
        self.high = 0
        self.frac = 0.0              # size of the bet currently faced, as a share of the pot
        self.aggressor = {}          # street -> last seat to bet or raise
        self.acted = set()
        self.made = []               # opponents' postflop bets and raises this hand: (seat, street, size bucket)

    # -- stats, shrunk -------------------------------------------------------
    def stat(self, seat, name, prof, bucket=1):
        """stab, cont (by bucket), cont_raise or raise for a seat, shrunk toward
        the same stat over the other seats, itself shrunk toward a default."""
        p = PARAMS
        prior = p["prior"]
        q = self.seats[seat]
        if name == "stab":
            default = min(0.9, max(0.05, prior["stab"] * prof["aggression"] / 0.40))
            a = q.stab
            t = self.all_stab
        elif name == "raise":
            default = min(0.5, max(0.01, prior["raise"] * prof["aggression"] / 0.40))
            a = q.raise_
            t = self.all_raise
        else:
            if not p["use_size_buckets"]:
                bucket = 1
            base = prior["cont_raise"] if name == "cont_raise" else prior["cont"][bucket]
            default = min(0.97, max(0.03, base * (1.0 - prof["fold_to_bet"]) / 0.55))
            if name == "cont_raise":
                return default
            a = q.cont[bucket]
            t = self.all_cont[bucket]
        pw = p["prior_weight_post"]
        mean = (t[0] - a[0] + default * pw) / (t[1] - a[1] + pw)
        return (a[0] + mean * pw) / (a[1] + pw)

    def bluff(self, seat, bucket):
        """Share of this seat's bets of this size that are bluffs: its own
        showdowns, shrunk toward the prior."""
        p = PARAMS
        if not p["use_size_buckets"]:
            bucket = 1
        a = self.seats[seat].bl[bucket]
        pw = p["prior_weight_bluff"]
        return min(0.7, max(0.03, (a[0] + p["bluff"][bucket] * pw) / (a[1] + pw)))

    def faced(self, seat):
        return self.seats[seat].raise_[1]

    def dead(self, seat):
        r = self.seats[seat].recent
        if len(r) < PARAMS["dead_window"]:
            return False
        facing = 0
        for passive, was_facing in r:
            if not passive:
                return False
            facing += was_facing
        return facing >= PARAMS["dead_facing"]

    def run_over(self, seat):
        h = self.seats[seat].hu
        return len(h) >= PARAMS["runover_min"] and sum(h) >= PARAMS["runover_share"] * len(h)


_tables = {}
_LAST = [None]       # the table used by the most recent decision, for observe()


def _profiles(profiles, seats, hero):
    """Contract profiles with preflop stats shrunk toward the table average."""
    prior = PARAMS["prior"]
    pw = PARAMS["prior_weight_pre"]
    keys = (("pfr", prior["pfr"]), ("vpip", prior["vpip"]), ("three_bet", prior["three_bet"]))
    raw = {}
    succ = [0.0, 0.0, 0.0]
    total = 0.0
    for s in range(seats):
        if s == hero:
            continue
        q = profiles.get(s) if isinstance(profiles, dict) else None
        if not isinstance(q, dict):
            q = {}
        hands = q.get("hands") or 0
        hands = hands if isinstance(hands, (int, float)) else 0
        vals = []
        for k, default in keys + (("aggression", 0.40), ("fold_to_bet", 0.45)):
            x = q.get(k)
            vals.append(float(x) if isinstance(x, (int, float)) and 0.0 <= x <= 1.0 else default)
        raw[s] = (hands, vals)
        total += hands
        for k in (0, 1, 2):
            succ[k] += vals[k] * hands
    out = {}
    for s, (hands, vals) in raw.items():
        o = {"aggression": vals[3], "fold_to_bet": vals[4]}
        for k, (name, default) in enumerate(keys):
            mine = vals[k] * hands
            mean = (succ[k] - mine + default * pw) / (total - hands + pw)
            o[name] = (mine + mean * pw) / (hands + pw)
        out[s] = o
    return out


def _count(seat_stat, table_stat, success):
    seat_stat[0] += success
    seat_stat[1] += 1
    table_stat[0] += success
    table_stat[1] += 1


def _bucket(frac):
    e = PARAMS["size_edges"]
    return 0 if frac <= e[0] else 1 if frac <= e[1] else 2 if frac <= e[2] else 3


def _seed(tb, state, profs, hero_ids):
    """Preflop ranges for every opponent still in, with our cards removed."""
    p = PARAMS
    n = tb.n
    sb, bb = tb.blinds
    mults = p["seat_mult"][-(n - 1):] if n > 1 else (1.0,)
    folded = state["folded"]
    tb.ranges = {}
    for s in range(n):
        if folded[s] or s == state["seat"]:
            continue
        prof = profs[s]
        mult = 1.0
        if p["use_seat_width"] and bb is not None and s != bb:
            k = (s - bb - 1) % n
            if k < len(mults):
                mult = mults[k]
        width = min(p["open_max"], max(p["open_min"], prof["pfr"] * mult))
        w = list(_pool(tb.pre.get(s, "check"), width, prof["vpip"], prof["three_bet"]))
        for c in hero_ids:
            for i in _WITH[c]:
                w[i] = 0.0
        tb.ranges[s] = _Range(w)


def _advance(tb, state, profs, stats_only=False):
    """Process history entries not seen yet: replay the pot, count each
    opponent's actions, and queue the range update each action calls for.
    The queued updates are cheap to make and are only carried out, by
    _update_ranges, when a decision needs the ranges. With stats_only (the
    hand is over) the actions are counted and nothing is queued."""
    p = PARAMS
    hero = state["seat"]
    history = state["history"]
    seats = tb.seats
    pending = tb.pending
    want = not stats_only
    for h in history[tb.done:]:
        seat, street, action, amount = h["seat"], h["street"], h["action"], h.get("amount") or 0
        if street != tb.street:
            tb.street = street
            tb.bets = {}
            tb.high = 0
            tb.frac = 0.0
            tb.acted = set()
        bets = tb.bets
        mine = bets.get(seat, 0)
        if action in ("small_blind", "big_blind"):
            tb.blinds[action == "big_blind"] = seat
            bets[seat] = amount
            tb.pot += amount
            if amount > tb.high:
                tb.high = amount
            continue
        if street == "preflop":
            if action == "raise":
                tb.pre[seat] = "3bet" if tb.pre_raises else "open"
                tb.pre_raises += 1
                tb.aggressor[street] = seat
                tb.pot += amount - mine
                bets[seat] = tb.high = amount
            elif action == "call":
                if tb.pre.get(seat) not in ("open", "3bet"):
                    tb.pre[seat] = "call" if tb.pre_raises else "limp"
                tb.pot += amount
                bets[seat] = mine + amount
            elif action == "check":
                tb.pre.setdefault(seat, "check")
            continue

        facing = tb.high > mine
        bucket_faced = _bucket(tb.frac)
        like = None
        q = seats[seat]
        if action == "raise":
            frac = (amount - tb.high) / float(max(1, tb.pot + tb.high - mine))
            b = _bucket(frac) if p["use_size_buckets"] else 1
            if seat != hero:
                if want:
                    like = _aggr(tb.stat(seat, "raise" if facing else "stab", profs[seat]), tb.bluff(seat, b))
                if facing:
                    _count(q.cont[bucket_faced], tb.all_cont[bucket_faced], 1)
                    _count(q.raise_, tb.all_raise, 1)
                else:
                    _count(q.stab, tb.all_stab, 1)
                q.recent.append((False, facing))
                tb.made.append((seat, street, b))
            tb.pot += amount - mine
            bets[seat] = tb.high = amount
            tb.frac = frac
            tb.aggressor[street] = seat
        elif action == "call":
            if seat != hero:
                if want:
                    prof = profs[seat]
                    cont = tb.stat(seat, "cont", prof, bucket_faced)
                    rf = tb.stat(seat, "raise", prof)
                    like = (1.0 - cont, p["call_below_like"], 1.0, 1.0 - min(rf, cont * 0.8), p["call_raise_like"])
                _count(q.cont[bucket_faced], tb.all_cont[bucket_faced], 1)
                _count(q.raise_, tb.all_raise, 0)
                q.recent.append((False, True))
            tb.pot += amount
            bets[seat] = mine + amount
        elif action == "check":
            if seat != hero:
                if want:
                    t, lo, hi = _aggr(tb.stat(seat, "stab", profs[seat]), tb.bluff(seat, 1))
                    like = (t, 1.0 - lo, 1.0 - hi)
                _count(q.stab, tb.all_stab, 0)
                q.recent.append((True, False))
        elif action == "fold":
            if seat != hero and facing:
                _count(q.cont[bucket_faced], tb.all_cont[bucket_faced], 0)
                _count(q.raise_, tb.all_raise, 0)
                q.recent.append((True, True))
        tb.acted.add(seat)

        if like is not None:
            pending.append((seat, street, action == "check", like))
    tb.done = len(history)


def _update_ranges(tb, state, profs, hero_ids, t0):
    """Carry out the queued range updates for opponents still in. Updates for
    checks are dropped once the decision has run past update_ms."""
    if tb.ranges is None:
        _seed(tb, state, profs, hero_ids)
    pending = tb.pending
    if not pending:
        return
    board = state["board"]
    folded = state["folded"]
    limit = t0 + PARAMS["update_ms"] / 1000.0
    for seat, street, is_check, like in pending:
        if folded[seat]:
            continue
        rg = tb.ranges.get(seat)
        if rg is None:
            continue
        if is_check and _CLOCK() > limit:
            STATS["skipped_updates"] += 1
            continue
        if rg.street != street:
            st = tb.streets.get(street)
            if st is None:
                st = tb.streets[street] = _street([_ID[c] for c in board[:_BOARD_LEN[street]]])
            rg.enter(street, st)
        rg.apply(*like)
    del pending[:]


# --------------------------------------------------------------------------
# 3. One set of trials
# --------------------------------------------------------------------------

_schedules = {}


def _schedule(scale):
    """For each trial, in order of the main opponent's percentile: its band,
    the slice of the band it is drawn from (start, width), its weight, and the
    running sum of the weights. Each band is cut into as many equal slices as
    it has trials, so the draws are spread evenly inside the band too."""
    key = int(scale * 200 + 0.5)
    sched = _schedules.get(key)
    if sched is None:
        band, edges, weights = [], [], []
        for b, (lo, hi, n) in enumerate(PARAMS["bands"]):
            n = max(2, int(n * key / 200.0 + 0.5))
            step = (hi - lo) / n
            band += [b] * n
            edges += [(lo + k * step, step) for k in range(n)]
            weights += [step] * n
        sched = _schedules[key] = (band, edges, weights, list(accumulate(weights, initial=0.0)))
    return sched


class _Trials:
    """n trials, in order of the main opponent's percentile.

    Against one opponent: s[t] is their percentile in their own range, r[t]
    hero's showdown share (1, 0.5 or 0), and `hu` holds running sums of weight
    and of weight times share, so any "hands above this percentile" question is
    two lookups.

    Against several, everything is held by opponent (main opponent first):
    s[j][t] is opponent j's percentile and r[j][t] a code for hero's result
    against them, 1 ahead, 8 tied, 64 behind. Adding the codes of the
    opponents who matter gives, in one number per trial, how many of them hero
    beats, ties and loses to. band[t] is the trial's band and mass[b] the
    weight of one trial in band b."""
    __slots__ = ("n", "opps", "w", "s", "r", "hu", "band", "mass")


def _hero_span(st, hidx):
    """Places in the street's order of the hands that tie hero: [lo, hi).
    Only used on the river, where equal seff means equal hands."""
    order = st.order
    hv = _seff(st, hidx)
    lo, hi = 0, len(order)
    while lo < hi:
        mid = (lo + hi) >> 1
        if _seff(st, order[mid]) < hv:
            lo = mid + 1
        else:
            hi = mid
    first = lo
    hi = len(order)
    while lo < hi:
        mid = (lo + hi) >> 1
        if _seff(st, order[mid]) <= hv:
            lo = mid + 1
        else:
            hi = mid
    return first, lo


def _make_trials(hero_ids, ids, st, ranges, deadline, scale):
    """All trials at once, one step at a time across them.

    River: an opponent's hand beats, ties or loses to hero according to where
    its percentile falls against two thresholds read off that opponent's
    cumulative weights, so no hands are drawn at all. (This treats opponents'
    hands as independent of each other; they already exclude hero's cards and
    the board.)

    Flop and turn: hands are drawn from the ranges and the remaining board is
    dealt by stepping through the unseen cards, so every card comes up equally
    often. Hands or boards that collide are drawn again one by one; a trial
    still colliding after three tries is dropped."""
    T = _Trials()
    T.opps = nopp = len(ranges)
    T.hu = None
    T.n = 0
    if _CLOCK() > deadline:
        return T
    band, edges, weights, wsum = _schedule(scale)
    n = len(band)
    rnd = _RNG.random
    h1, h2 = hero_ids
    hidx = _CIDX[(h1, h2) if h1 < h2 else (h2, h1)]
    U = [lo + wd * rnd() for lo, wd in edges]
    need = 5 - len(ids)
    dropped = None

    if need == 0:
        first, last = _hero_span(st, hidx)
        cols = []
        for k, rg in enumerate(ranges):
            cum, tot = rg.cum, rg.total
            a = cum[first - 1] / tot if first else 0.0
            b = cum[last - 1] / tot if last else 0.0
            if k == 0:
                if nopp == 1:
                    R = [1.0 if u < a else 0.5 if u < b else 0.0 for u in U]
                    break
                S = [U]
            else:
                U = [rnd() for _ in band]
                S.append(U)
            cols.append([1 if u < a else 8 if u < b else 64 for u in U])
    else:
        bis = bisect_right
        cbit, cks, css = _CBIT, _CK, _CS
        nf, flush, k5, s8 = _NF, _FLUSH, _K5, _S8
        order = st.opad
        cum, tot = ranges[0].cum, ranges[0].total
        I = [order[bis(cum, u * tot)] for u in U]
        used = [cbit[i] for i in I]
        S = [U]
        idx = [I]
        for rg in ranges[1:]:
            cum, tot = rg.cum, rg.total
            U = [rnd() for _ in band]
            I = [order[bis(cum, u * tot)] for u in U]
            B = [cbit[i] for i in I]
            for t in [t for t, (a, b) in enumerate(zip(used, B)) if a & b]:
                a = used[t]
                for _ in (0, 1, 2):
                    u = rnd()
                    i = order[bis(cum, u * tot)]
                    if not a & cbit[i]:
                        U[t] = u
                        I[t] = i
                        B[t] = cbit[i]
                        break
                else:
                    # Dropped below; its cards still count as used so the board avoids them.
                    if dropped is None:
                        dropped = set()
                    dropped.add(t)
            used = [a | b for a, b in zip(used, B)]
            S.append(U)
            idx.append(I)

        bk = bs = 0
        bsm = [0, 0, 0, 0]
        bsm_count = [0, 0, 0, 0]
        taken = set(hero_ids)
        for c in ids:
            bk += k5[c]
            bs += s8[c]
            bsm[c & 3] |= 1 << (c >> 2)
            bsm_count[c & 3] += 1
            taken.add(c)
        deck = [c for c in range(52) if c not in taken]
        nd = len(deck)
        reps = n // (nd - 1) + 1
        hk = cks[hidx]
        hs = css[hidx]
        # First card: step through the deck from a random start with a random stride.
        off = int(rnd() * nd)
        stride = _STRIDES[nd][int(rnd() * len(_STRIDES[nd]))]
        cyc = [deck[(off + stride * t) % nd] for t in range(nd)]
        X = (cyc * reps)[:n]
        if need == 1:
            Y = [-1] * n
            kc = [bk + k5[x] for x in cyc]
            RK = (kc * reps)[:n]
            RS = ([bs + s8[x] for x in cyc] * reps)[:n]
            HV = ([nf[k + hk] for k in kc] * reps)[:n]
            clash = [t for t, (x, a) in enumerate(zip(X, used)) if a >> x & 1]
        else:
            # Second card: the same over a cycle one card shorter, so the pairs do not repeat.
            off = int(rnd() * nd)
            stride = _STRIDES[nd][int(rnd() * len(_STRIDES[nd]))]
            cyc2 = [deck[(off + stride * t) % nd] for t in range(nd - 1)]
            Y = (cyc2 * reps)[:n]
            RK = list(map(add, ([bk + k5[x] for x in cyc] * reps)[:n], ([k5[y] for y in cyc2] * reps)[:n]))
            RS = list(map(add, ([bs + s8[x] for x in cyc] * reps)[:n], ([s8[y] for y in cyc2] * reps)[:n]))
            HV = None
            clash = [t for t, (x, y, a) in enumerate(zip(X, Y, used)) if x == y or a >> x & 1 or a >> y & 1]
        for t in clash:
            a = used[t]
            x = deck[int(rnd() * nd)]
            while a >> x & 1:
                x = deck[int(rnd() * nd)]
            X[t] = x
            RK[t] = bk + k5[x]
            RS[t] = bs + s8[x]
            if need == 2:
                y = deck[int(rnd() * nd)]
                while y == x or a >> y & 1:
                    y = deck[int(rnd() * nd)]
                Y[t] = y
                RK[t] += k5[y]
                RS[t] += s8[y]
            else:
                HV[t] = nf[RK[t] + hk]
        if HV is None:
            HV = [nf[k + hk] for k in RK]
        # Boards on which somebody could hold a flush; elsewhere the rank tables are enough.
        flushy = [t for t, rs in enumerate(RS) if _FLUSH3[rs]] if max(bsm_count) + need >= 3 else ()
        for t in flushy:
            f = flush[RS[t] + hs]
            if f >= 0:
                HV[t] = _with_flush(HV[t], f, bsm[f], X[t], Y[t], h1, h2)
        cols = []
        for I in idx:
            V = [nf[k + cks[i]] for k, i in zip(RK, I)]
            for t in flushy:
                i = I[t]
                f = flush[RS[t] + css[i]]
                if f >= 0:
                    V[t] = _with_flush(V[t], f, bsm[f], X[t], Y[t], _C1[i], _C2[i])
            if nopp == 1:
                R = [1.0 if h > v else 0.5 if h == v else 0.0 for h, v in zip(HV, V)]
            else:
                cols.append([1 if h > v else 8 if h == v else 64 for h, v in zip(HV, V)])

    if nopp == 1:
        T.n = n
        T.w = weights
        T.s = S0 = U if need == 0 else S[0]
        T.r = R
        T.hu = (S0, wsum, list(accumulate(map(mul, weights, R), initial=0.0)))
        return T
    if dropped:
        keep = [t for t in range(n) if t not in dropped]
        S = [[U[t] for t in keep] for U in S]
        cols = [[c[t] for t in keep] for c in cols]
        band = [band[t] for t in keep]
        n = len(band)
    count = Counter(band)
    T.n = n
    T.w = None
    T.s = S
    T.r = cols
    T.band = band
    T.mass = [(hi - lo) / count[b] if count[b] else 0.0 for b, (lo, hi, _) in enumerate(PARAMS["bands"])]
    return T


def _strides():
    """For a deck of n cards: the step sizes that visit every card."""
    def coprime(a, b):
        while b:
            a, b = b, a % b
        return a == 1
    return {n: [k for k in range(1, n) if coprime(k, n)] for n in range(40, 50)}


_STRIDES = _strides()


def _with_flush(v, f, m, x, y, c1, c2):
    for c in (x, y, c1, c2):
        if c >= 0 and c & 3 == f:
            m |= 1 << (c >> 2)
    fvv = _FV[m]
    return fvv if fvv > v else v


def equity(T, lo=None):
    """Showdown share against all live opponents; with `lo`, only against the
    main opponent's hands at or above that percentile."""
    if T.hu is not None:
        S, W, H = T.hu
        k = bisect_left(S, lo) if lo is not None else 0
        den = W[-1] - W[k]
        return (H[-1] - H[k]) / den if den > 0.0 else None
    k = bisect_left(T.s[0], lo) if lo is not None else 0
    cols = T.r
    tot = cols[0][k:] if k else cols[0]
    for c in cols[1:]:
        tot = map(add, tot, c[k:] if k else c)
    mass = T.mass
    num = den = 0.0
    for (b, code), cnt in Counter(zip(T.band[k:] if k else T.band, tot)).items():
        x = mass[b] * cnt
        den += x
        if code < 64:
            num += x / (1 + (code >> 3))
    return num / den if den > 0.0 else None


def ev_bet(T, pot, cost, adds, conts, raise_top=0.0, strong=True):
    """Expected chips from putting `cost` more in, against opponents who each
    continue with the top conts[j] of their range and then add adds[j].
    Every caller's chips are counted. Heads-up, raise_top is the share of the
    opponent's range that raises: when hero is not strong, those trials lose
    the bet. Returns (ev, equity when called, chance of being called)."""
    if T.hu is not None:
        S, W, H = T.hu
        wsum = W[-1]
        if wsum <= 0.0:
            return 0.0, None, 0.0
        k = bisect_left(S, 1.0 - conts[0])
        kr = bisect_left(S, 1.0 - raise_top, k) if raise_top and not strong else len(S)
        cw = W[kr] - W[k]
        cs = H[kr] - H[k]
        ev = W[k] * pot + cs * (pot + cost + adds[0]) - (wsum - W[k]) * cost
        return ev / wsum, (cs / cw if cw > 0.0 else None), cw / wsum
    # One number per trial: the result codes of the callers, plus (above bit 9)
    # the chips they add when those differ between opponents.
    same = min(adds) == max(adds)
    tot = None
    for S, C, cont, a in zip(T.s, T.r, conts, adds):
        cut = 1.0 - cont
        if same:
            col = [c if s >= cut else 0 for s, c in zip(S, C)]
        else:
            a <<= 9
            col = [c + a if s >= cut else 0 for s, c in zip(S, C)]
        tot = col if tot is None else map(add, tot, col)
    mass = T.mass
    add0 = adds[0]
    ev = wsum = cw = cs = 0.0
    for (b, code), cnt in Counter(zip(T.band, tot)).items():
        x = mass[b] * cnt
        wsum += x
        if not code:
            ev += x * pot
            continue
        cw += x
        res = code & 511
        if res >= 64:
            ev -= x * cost
            continue
        ties = res >> 3
        extra = add0 * ((res & 7) + ties) if same else code >> 9
        sh = 1.0 / (1 + ties)
        cs += x * sh
        ev += x * (sh * (pot + cost + extra) - cost)
    if wsum <= 0.0:
        return 0.0, None, 0.0
    return ev / wsum, (cs / cw if cw > 0.0 else None), cw / wsum


def ev_check(T, pot, eq, closing, hu_stab, realize):
    """Expected chips from checking. Closing the action on the river: equity
    times the pot. Heads-up with the opponent still to act: they bet stab_size
    of the pot with hu_stab's likelihood and hero calls only when that is worth
    it. Otherwise equity times the pot times a realization factor."""
    if closing:
        return eq * pot * (realize if realize else 1.0)
    if hu_stab is None:
        return eq * pot * realize
    thr, lo, hi = hu_stab
    bet = PARAMS["stab_size"] * pot
    rnd = _RNG.random
    wsum = bw = bs_ = cs = 0.0
    for x, s0, sh in zip(T.w, T.s, T.r):
        wsum += x
        if rnd() < (hi if s0 >= thr else lo):
            bw += x
            bs_ += x * sh
        else:
            cs += x * sh
    if wsum <= 0.0:
        return eq * pot * realize
    call_ev = 0.0
    if bw > 0.0:
        call_ev = max(0.0, (bs_ / bw) * (pot + 2 * bet) - bet) * bw
    return (cs * pot * realize + call_ev) / wsum


# --------------------------------------------------------------------------
# 4-6. Choosing
# --------------------------------------------------------------------------

def _raise_to(state, fraction):
    """Raise-to amount for a bet of `fraction` of the pot after calling; None is the maximum."""
    lo, hi = state["min_raise_to"], state["max_raise_to"]
    if fraction is None:
        return hi
    target = max(state["bets"]) + int(fraction * (state["pot"] + state["to_call"]))
    return max(lo, min(hi, target))


def required_equity(price, streets_left, oop, behind, stack_share, structural=True, scale=1.0):
    """Equity needed to call. `price` is to_call / (pot + to_call). `scale`
    shrinks the margins that are about the bettor (streets left, position,
    stack share); the margin for players still to act behind is left alone."""
    if not structural:
        return price
    p = PARAMS
    return (price + scale * (p["margin_street"] * streets_left + (p["margin_oop"] if oop else 0.0)
                             + p["margin_stack"] * stack_share)
            + p["margin_behind"] * behind)


def choose_no_bet(state, T, tb, opps, profs, eq, strong, closing, in_position, streets_left, bluff_freq, roll):
    """bluff_freq is the set frequency for betting this hand as a bluff in this
    spot (0 for a hand that is neither a draw nor worthless) and roll the
    decision's random number in [0, 1)."""
    p = PARAMS
    passive = {"action": "check"}
    if "raise" not in state["legal_actions"]:
        return passive
    pot = state["pot"]
    seat = state["seat"]
    stack = state["stacks"][seat]
    my_bet = state["bets"][seat]
    n = len(opps)
    hu = n == 1
    rnd = _RNG.random
    realize = p["realize_last"] if in_position else p["realize_not_last"]
    stab = None
    if hu and not closing:
        stab = _aggr(tb.stat(opps[0], "stab", profs[opps[0]]), tb.bluff(opps[0], 1))
    base = ev_check(T, pot, eq, closing, stab, 0.0 if closing and not streets_left else realize)
    sizes = list(p["sizes"])
    if stack <= p["allin_spr"] * pot:
        sizes.append(None)
    values = []      # (ev, target) for sizes that are ahead when called and beat checking
    others = []      # (gain, target, index into sizes) for the rest
    seen = set()
    for k, f in enumerate(sizes):
        target = _raise_to(state, f)
        cost = target - my_bet
        if cost <= 0 or target in seen:
            continue
        seen.add(target)
        b = _bucket(cost / float(max(pot, 1)))
        conts = [tb.stat(j, "cont", profs[j], b) for j in opps]
        rt = tb.stat(opps[0], "raise", profs[opps[0]]) if hu and p["use_raise_risk"] else 0.0
        ev, eq_called, _ = ev_bet(T, pot, cost, [cost] * n, conts, rt, strong)
        gain = ev - base
        if eq_called is not None and eq_called >= 0.5:
            if gain > p["value_gain"] * pot * n:
                values.append((ev, target))
        elif cost < p["commit_frac"] * stack:
            others.append((gain, target, k))

    if values:
        ev, target = max(values)
        if len(values) > 1 and rnd() < p["size_jitter"]:
            # Sometimes a size that is nearly as good, so that size says less about the hand.
            near = [t for e, t in values if t != target and e >= ev - p["size_jitter_tol"] * pot]
            if near:
                target = near[int(rnd() * len(near))]
        return {"action": "raise", "amount": target}

    if not others or not p["use_bluffs"] or n > p["bluff_opps_max"]:
        return passive
    freq = bluff_freq
    best_gain = max(others)[0]
    if hu and tb.faced(opps[0]) >= p["bluff_min_seen"] and best_gain > p["bluff_gain"] * pot:
        # This opponent folds enough that betting clearly beats checking: bet more often.
        freq = max(freq, min(p["bluff_max_freq"], best_gain / (p["bluff_full"] * max(pot, 1))))
    if roll >= freq:
        return passive
    ok = [(g, t, k) for g, t, k in others if g >= p["bluff_floor"] * pot]
    if not ok:
        return passive
    mix = p["bluff_size_mix"]
    weights = [mix[k] if k < len(mix) else 0.0 for _, _, k in ok]
    total = sum(weights)
    if total <= 0.0:
        target = max(ok)[1]
    else:
        x = rnd() * total
        target = ok[-1][1]
        for (_, t, _), w in zip(ok, weights):
            x -= w
            if x < 0.0:
                target = t
                break
    STATS["mixed_bluffs"] += 1
    return {"action": "raise", "amount": target}


def choose_facing_bet(state, T, tb, opps, profs, eq, bettor, behind, in_position, streets_left, combo_draw):
    p = PARAMS
    legal = state["legal_actions"]
    pot = state["pot"]
    to_call = state["to_call"]
    seat = state["seat"]
    stack = state["stacks"][seat]
    bets = state["bets"]
    my_bet = bets[seat]
    hu = len(opps) == 1
    price = to_call / float(pot + to_call)
    structural = not (p["use_runover_guard"] and hu and bettor is not None and tb.run_over(bettor))
    scale = 1.0
    if p["use_aggro_margin"] and bettor is not None and (state.get("raises_this_street") or 1) <= 1:
        often = tb.stat(bettor, "stab", profs[bettor])
        scale = min(1.0, max(0.0, (p["aggro_hi"] - often) / (p["aggro_hi"] - p["aggro_lo"])))
    need = required_equity(price, streets_left, not in_position, behind,
                           min(1.0, to_call / float(max(stack, 1))), structural, scale)
    ev_call = eq * (pot + to_call) - to_call
    action = {"action": "call"} if eq >= need else {"action": "fold"}
    if "raise" in legal:
        high = max(bets)
        target = max(state["min_raise_to"], min(state["max_raise_to"], int(p["raise_mult"] * high)))
        cost = target - my_bet
        allin = target >= state["max_raise_to"] and cost >= stack
        conts = []
        for j in opps:
            c = tb.stat(j, "cont_raise", profs[j])
            if allin:
                c = min(c, tb.stat(j, "cont", profs[j], 3))
            conts.append(c)
        adds = [max(0, target - bets[j]) for j in opps]
        ev, eq_called, _ = ev_bet(T, pot, cost, adds, conts)
        ahead = eq_called is not None and eq_called >= 0.5
        if cost < p["commit_frac"] * stack or ahead:
            alt = max(ev_call, 0.0)
            if eq_called is not None and eq_called >= p["raise_eq"] and eq >= need \
                    and ev > ev_call + p["raise_gain"] * pot:
                action = {"action": "raise", "amount": target}
            elif combo_draw and hu and streets_left and ev > alt + p["draw_raise_gain"] * pot:
                action = {"action": "raise", "amount": target}
    if hu and bettor is not None:
        tb.seats[bettor].hu.append(action["action"] == "fold")
    return action


def _fallback(state, seff, opponents):
    """Step 8: hero's seff by size of bet faced. No trials needed."""
    legal = state.get("legal_actions", ())
    passive = {"action": "check" if "check" in legal else "fold"}
    if seff is None:
        return passive
    row = sum(1 for x in _FALLBACK_ROWS if seff >= x)
    if opponents >= 3 and row:
        row -= 1
    to_call = state.get("to_call") or 0
    if to_call <= 0:
        col = 0
    else:
        price = to_call / float(state["pot"] + to_call)
        col = 1 if price <= 0.22 else 2 if price <= 0.30 else 3
    code = _FALLBACK[row][col]
    if code in "br" and "raise" in legal:
        return {"action": "raise", "amount": _raise_to(state, 0.66)}
    if code != "x" and "call" in legal:
        return {"action": "call"}
    return passive


def _decide(state, profiles, out):
    t0 = _CLOCK()
    p = PARAMS
    legal = state["legal_actions"]
    seat = state["seat"]
    street = state["street"]
    board = state["board"]
    folded = state["folded"]
    n = len(folded)
    passive = {"action": "check" if "check" in legal else "fold"}
    if len(board) < 3:
        return passive

    tb = _tables.get(seat)
    hand = state["hand_number"]
    if tb is None or tb.n != n or tb.hand is None or hand < tb.hand:
        tb = _tables[seat] = _Table(n)          # a new round: forget everything
    if hand != tb.hand or tb.done > len(state["history"]):
        tb.hand = hand
        tb.reset_hand()
    tb.seat = seat
    _LAST[0] = tb

    ids = [_ID[c] for c in board]
    hero_ids = [_ID[c] for c in state["hole_cards"]]
    st = tb.streets.get(street)
    if st is None:
        st = tb.streets[street] = _street(ids)
    h1, h2 = hero_ids
    out["seff"] = seff = _seff(st, _CIDX[(h1, h2) if h1 < h2 else (h2, h1)])

    profs = tb.profs
    if profs is None:
        profs = tb.profs = _profiles(profiles, n, seat)
    _advance(tb, state, profs)
    opps = [s for s in range(n) if not folded[s] and s != seat]
    out["opps"] = len(opps)
    if not opps:
        return passive
    to_call = state["to_call"]

    # Dead bots: minimum bet every time nobody has bet.
    if p["use_dead_bot"] and to_call <= 0 and "raise" in legal and all(tb.dead(j) for j in opps):
        return {"action": "raise", "amount": state["min_raise_to"]}

    # Hopeless hand against two or more opponents: the full calculation always
    # comes out as check, or as fold unless the bet is tiny, so skip it. Bluffs
    # are heads-up only and a value bet needs to be ahead when called. The
    # queued range updates stay queued in case a later street needs them.
    roll = _RNG.random()
    bluff_freq = 0.0
    if to_call <= 0 and p["use_bluffs"] and len(opps) <= p["bluff_opps_max"] and "raise" in legal:
        kind = None
        if street != "river" and _is_draw(hero_ids, ids):
            kind = "draw"
        elif seff < p["bluff_air"]:
            lead = False
            if street not in tb.aggressor:
                for name in ("turn", "flop", "preflop")[3 - len(ids) + 2:]:
                    if name in tb.aggressor:
                        lead = tb.aggressor[name] == seat
                        break
            kind = ("cbet" if street == "flop" else "barrel") if lead else "probe"
        if kind:
            bluff_freq = p["bluff_freq"][kind][0 if len(opps) == 1 else 1]

    if p["use_shortcut"] and len(opps) >= 2 and seff < p["shortcut_seff"]:
        if to_call <= 0 and roll >= bluff_freq:
            STATS["shortcuts"] += 1
            return {"action": "check"}
        if to_call >= p["shortcut_price"] * (state["pot"] + to_call):
            STATS["shortcuts"] += 1
            return {"action": "fold"}

    _update_ranges(tb, state, profs, hero_ids, t0)

    # The main opponent: the bettor, or the player we would be betting into.
    bettor = tb.aggressor.get(street)
    if bettor not in opps:
        bettor = None
    prim = bettor
    if prim is None:
        for name in ("turn", "flop", "preflop"):
            a = tb.aggressor.get(name)
            if a in opps:
                prim = a
                break
        else:
            prim = min(opps, key=lambda j: (j - seat) % n)
    opps.remove(prim)
    opps.insert(0, prim)
    ranges = []
    for j in opps:
        rg = tb.ranges.get(j)
        if rg is None:
            rg = tb.ranges[j] = _Range(list(_pool("check", 0.15, 0.30, 0.05)))
            for c in hero_ids:
                for i in _WITH[c]:
                    rg.wc[i] = 0.0
        if rg.street != street:
            rg.enter(street, st)
        rg.ready()
        if rg.total <= 0.0:
            # Everything was ruled out: start that seat again from any two cards.
            rg.wc = [0.0 if (_C1[i] in hero_ids or _C2[i] in hero_ids) else 1.0 for i in range(_NC)]
            rg.zeroed = 0
            rg.enter(street, st)
            rg.ready()
        ranges.append(rg)

    want = (p["trials_hu"] if len(opps) == 1 else p["trials_multi"])[len(ids) - 3]
    if p["opp_samples"] and len(opps) * want > p["opp_samples"]:
        want = p["opp_samples"] // len(opps)
    scale = _SCALE * want / 200.0
    T = _make_trials(hero_ids, ids, st, ranges, t0 + p["deadline_ms"] / 1000.0, scale)
    out["trials"] = T.n
    if T.n < p["min_share"] * 200.0 * scale:
        return None
    eq = equity(T)
    if eq is None:
        return None
    top = equity(T, p["top"])
    strong = top is not None and top >= 0.5

    button = state["button"]
    my_pos = (seat - button - 1) % n
    in_position = all((j - button - 1) % n < my_pos for j in opps)
    streets_left = _STREETS_LEFT[street]
    stacks = state["stacks"]
    if to_call <= 0:
        behind = sum(1 for j in opps if j not in tb.acted and stacks[j] > 0)
        return choose_no_bet(state, T, tb, opps, profs, eq, strong, behind == 0, in_position, streets_left,
                             bluff_freq, roll)
    bets = state["bets"]
    high = max(bets)
    behind = sum(1 for j in opps if j != bettor and bets[j] < high and stacks[j] > 0)
    combo = street != "river" and seff >= p["floor_combo"][0 if street == "flop" else 1] \
        and _is_combo_draw(hero_ids, ids)
    return choose_facing_bet(state, T, tb, opps, profs, eq, bettor, behind, in_position, streets_left, combo)


def _is_draw(hero_ids, ids):
    """Flush draw or open-ended straight draw, with no straight or flush made yet."""
    mask = 0
    suits = [0, 0, 0, 0]
    for c in hero_ids + ids:
        mask |= 1 << (c >> 2)
        suits[c & 3] += 1
    if max(suits) >= 5 or _STOP[mask] >= 0:
        return False
    return any(suits[c & 3] == 4 for c in hero_ids) or _OUTS[mask] >= 2


def _is_combo_draw(hero_ids, ids):
    """Flush draw plus a straight draw, with no straight or flush made yet."""
    mask = 0
    suits = [0, 0, 0, 0]
    for c in hero_ids + ids:
        mask |= 1 << (c >> 2)
        suits[c & 3] += 1
    fd = any(suits[c & 3] == 4 for c in hero_ids)
    return fd and _STOP[mask] < 0 and _OUTS[mask] > 0


def decide(state, profiles):
    t0 = _CLOCK()
    out = {}
    STATS["decisions"] += 1
    try:
        action = _decide(state, profiles, out)
        if action is None:
            STATS["fallback_trials"] += 1
    except Exception as exc:
        if PARAMS["raise_errors"]:
            raise
        name = type(exc).__name__
        STATS["exceptions"][name] = STATS["exceptions"].get(name, 0) + 1
        STATS["fallback_error"] += 1
        action = None
    if action is None:
        if "seff" not in out:
            STATS["fallback_no_table"] += 1
        action = _fallback(state, out.get("seff"), out.get("opps", 1))
    STATS["trials"] += out.get("trials", 0)
    ms = (_CLOCK() - t0) * 1000.0
    if ms > STATS["slowest_ms"]:
        STATS["slowest_ms"] = ms
    return action


def observe(summary):
    """Optional: call with the on_hand_end summary of every hand.

    Counts the opponents' actions this module was not shown while deciding,
    and for each opponent hand shown at showdown records whether each of its
    bets was a bluff. Never raises unless PARAMS["raise_errors"] is set. Safe
    to leave uncalled: the module then learns only from what decide() sees."""
    try:
        _observe(summary)
    except Exception:
        if PARAMS["raise_errors"]:
            raise
        STATS["observe_errors"] += 1


def _observe(summary):
    tb = _LAST[0]
    if tb is None or not isinstance(summary, dict):
        return
    history = summary.get("history") or []
    hand = summary.get("hand_number")
    if not isinstance(hand, int) or (tb.hand is not None and hand < tb.hand):
        _LAST[0] = None          # a new round: wait for its first decision
        return
    if hand != tb.hand or tb.done > len(history):
        tb.hand = hand
        tb.reset_hand()
    _advance(tb, {"seat": tb.seat, "history": history}, None, stats_only=True)
    STATS["observed_hands"] += 1
    shown = summary.get("shown") or {}
    board = summary.get("board") or []
    if not shown or len(board) < 3 or not tb.made:
        return
    limit = PARAMS["bluff_seff"]
    for key, cards in shown.items():
        seat = int(key)
        if seat == tb.seat or not (0 <= seat < tb.n) or len(cards) != 2:
            continue
        c1, c2 = _ID[cards[0]], _ID[cards[1]]
        idx = _CIDX[(c1, c2) if c1 < c2 else (c2, c1)]
        counts = tb.seats[seat].bl
        for who, street, bucket in tb.made:
            if who != seat or len(board) < _BOARD_LEN[street]:
                continue
            st = tb.streets.get(street)
            if st is None:
                st = tb.streets[street] = _street([_ID[c] for c in board[:_BOARD_LEN[street]]])
            counts[bucket][1] += 1
            STATS["shown_bets"] += 1
            if _seff(st, idx) < limit:
                counts[bucket][0] += 1
                STATS["shown_bluffs"] += 1
