"""Postflop strategy "ranges_v2": ranges, one set of stratified trials, one EV table.

Experimental: not imported by src/postflop.py and not bundled by build.py.

Build each opponent's range -> draw one set of stratified trials -> compare the
expected chips of every action from those trials -> fall back safely.

  1 Board table   every two-card hand on the current board: its strength now
                  and the share of other hands it beats (seff), with floors for
                  draws. Built once per street and kept until the hand ends.
  2 Ranges        a weight per hand for each opponent, seeded from their
                  preflop action and seat, then multiplied by the likelihood of
                  each postflop action given how often that opponent takes it.
  3 Trials        200 trials stratified on the main opponent's strength.
                  Showdown shares split ties by the number of players tied.
  4 No bet        expected chips of checking and of each bet size, counting
                  every caller; value bets and bluffs pass different gates.
  5 Facing a bet  pot odds plus structural margins; raise when it beats calling.
  6 Commitment    no separate rule: a stack-share margin on calls, and bets or
                  raises for half the stack need to be ahead when called.
  7 Stats         shrunk toward a prior from the first hand. Counted here from
                  the action histories this module is shown, because the
                  profiles in the team contract do not carry them.
  8 Fallback      hero's seff by size of bet faced. Reasons are counted in STATS.

The module keeps state per own seat across the hands of a round (opponent
counts) and within a hand (ranges and board tables). It needs no other module.

Not done here, and why:
  - Bluff share is not updated from showdowns: decide() never sees shown cards.
  - Actions after our last decision in a hand are never seen, so counts lag.
  - No search over future betting. A realization factor on checking and the
    per-street margin stand in for it.
"""
import random
import time
from bisect import bisect_right
from collections import deque
from itertools import accumulate

PARAMS = {
    # time
    "deadline_ms": 3.0,            # trials stop this long after decide() starts
    "update_ms": 1.4,              # after this, range updates for checks are skipped
    "trials": 200, "min_trials": 120,
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
    "commit_frac": 0.5,
    # facing a bet
    "margin_street": 0.015, "margin_oop": 0.02, "margin_behind": 0.025, "margin_stack": 0.04,
    "raise_mult": 3.0, "raise_eq": 0.65, "raise_gain": 0.03, "draw_raise_gain": 0.10,
    "runover_min": 12, "runover_share": 0.70,
    "dead_window": 40, "dead_facing": 10,
    # switches for the calibration changes
    "use_size_buckets": True, "use_seat_width": True, "use_raise_risk": True,
    "use_runover_guard": True, "use_dead_bot": True, "use_bluffs": True,
    # set True to let exceptions out (tests and CI); normally they become the fallback action
    "raise_errors": False,
}

# Counters for the promotion gate. Read them after a run; nothing resets them.
STATS = {"decisions": 0, "fallback_trials": 0, "fallback_error": 0, "fallback_no_table": 0,
         "exceptions": {}, "trials": 0, "skipped_updates": 0, "slowest_ms": 0.0}

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
    multiset. _FV: flush-suit rank mask -> value. _FLUSH / _FOUR: base-8
    suit-count key -> the suit with five or more / exactly four cards, or -1."""
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
    four = [-1] * 4096
    for key in range(4096):
        for s in range(4):
            n = key >> (3 * s) & 7
            if n >= 5:
                flush[key] = s
            elif n == 4:
                four[key] = s
    return nf, fv, flush, four


_NF, _FV, _FLUSH, _FOUR = _build_tables()

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
_CSP = [(_C1[i] & 3) * 4 + (_C2[i] & 3) for i in range(_NC)]        # suit pair
_CRP = [(_C1[i] >> 2) * 13 + (_C2[i] >> 2) for i in range(_NC)]    # rank pair, low rank first


def _value(cards):
    """Value of the best five of 5-7 card ids. Higher wins. For tests and the
    rare flush path; the hot loops use the tables directly."""
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
    __slots__ = ("val", "seff", "order", "n")


def _street(ids):
    """Strength of every two-card hand on this board."""
    p = PARAMS
    nb = len(ids)
    bk = bs = bmask = 0
    bsuit = [0, 0, 0, 0]
    bsm = [0, 0, 0, 0]
    for c in ids:
        bk += _K5[c]
        bs += _S8[c]
        bmask |= 1 << (c >> 2)
        bsuit[c & 3] += 1
        bsm[c & 3] |= 1 << (c >> 2)
    get = _NF.get
    val = [get(bk + ck, -1) for ck in _CK]
    if max(bsuit) >= 3:
        # A flush is possible: redo the hands that have one.
        fv, flush, c1s, c2s = _FV, _FLUSH, _C1, _C2
        for i in [i for i, cs in enumerate(_CS) if flush[bs + cs] >= 0]:
            c1 = c1s[i]
            c2 = c2s[i]
            f = flush[bs + _CS[i]]
            m = bsm[f]
            if c1 & 3 == f:
                m |= 1 << (c1 >> 2)
            if c2 & 3 == f:
                m |= 1 << (c2 >> 2)
            if fv[m] > val[i]:
                val[i] = fv[m]
    for c in ids:
        for i in _WITH[c]:
            val[i] = -1
    live = [i for i, v in enumerate(val) if v >= 0]
    n = len(live)
    ordered = sorted([val[i] for i in live])
    share = {-1: 0.0}
    scale = 1.0 / (n - 1)
    k = 0
    while k < n:
        v = ordered[k]
        j = bisect_right(ordered, v, k)
        share[v] = (k + 0.5 * (j - k - 1)) * scale
        k = j
    if nb == 5:
        seff = [share[v] for v in val]
    else:
        col = 0 if nb == 3 else 1
        floors = (0.0, p["floor_gutshot"][col], p["floor_draw"][col],      # no flush draw: 0, 1, 2+ outs
                  p["floor_draw"][col], p["floor_combo"][col], p["floor_combo"][col])
        # A flush draw needs four of a suit with a hole card among them.
        fd = [0] * 16
        for s1 in range(4):
            for s2 in range(4):
                for s3 in range(4):
                    if bsuit[s3] < 4 and bsuit[s3] + (s1 == s3) + (s2 == s3) == 4:
                        fd[s1 * 4 + s2] = 3
        # Straight outs by rank pair: 0, 1 (gutshot) or 2 (open-ended); 0 once a straight is made.
        sd = [0] * 169
        for a in range(13):
            for b in range(a, 13):
                m = bmask | 1 << a | 1 << b
                if _STOP[m] < 0:
                    sd[a * 13 + b] = min(2, _OUTS[m])
        seff = []
        add = seff.append
        for v, sp, rp in zip(val, _CSP, _CRP):
            x = share[v]
            f = floors[fd[sp] + sd[rp]]
            add(f if f > x else x)
    st = _Street()
    st.val, st.seff, st.n = val, seff, n
    st.order = sorted(live, key=seff.__getitem__)
    return st


# --------------------------------------------------------------------------
# 2. Opponent ranges
# --------------------------------------------------------------------------

class _Range:
    """A weight per combination, with its live members in order of strength on
    one street (weakest first). A hand's place on the cumulative-weight axis is
    its percentile within this opponent's own range."""
    __slots__ = ("w", "mem", "total", "street", "cum")

    def __init__(self, weights):
        self.w = weights
        self.mem = None
        self.total = 0.0
        self.street = None
        self.cum = None

    def enter(self, name, st):
        w = self.w
        if self.mem is None:
            mem = [i for i in st.order if w[i] > 0.0]
        else:
            # Already filtered once: drop hands the new board card kills, then re-order.
            val = st.val
            mem = sorted([i for i in self.mem if val[i] >= 0], key=st.seff.__getitem__)
        self.mem = mem
        self.total = sum([w[i] for i in mem])
        self.street = name
        self.cum = None

    def apply(self, t1, l0, l1, t2=2.0, l2=0.0):
        """Multiply each hand's weight by the likelihood of an action: l0 below
        percentile t1, l1 from t1 to t2, l2 above t2."""
        w = self.w
        total = self.total
        if total <= 0.0:
            return
        a = t1 * total
        b = t2 * total
        cum = 0.0
        out = []
        for i in self.mem:
            x = w[i]
            mid = cum + 0.5 * x
            cum += x
            out.append(x * (l0 if mid < a else l1 if mid < b else l2))
        new = sum(out)
        if new <= 0.0:       # the action was impossible under the model: keep the old range
            return
        for i, x in zip(self.mem, out):
            w[i] = x
        self.total = new
        self.cum = None

    def ready(self):
        if self.cum is None:
            w = self.w
            self.cum = list(accumulate([w[i] for i in self.mem]))
            self.total = self.cum[-1] if self.cum else 0.0


def _aggr(freq, bluff_share):
    """Likelihood pieces for a bet or raise by a seat that takes it `freq` of
    the time. Value bets are freq * (1 - bluff_share) of the range, from the
    top, where hands bet value_bets of the time; everything below bets at a
    flat rate so that the average is freq. Returns (threshold, below, above)."""
    hi = PARAMS["value_bets"]
    freq = min(0.98, max(0.01, freq))
    top = min(0.999, freq * (1.0 - bluff_share) / hi)
    below = (freq - hi * top) / (1.0 - top)
    return 1.0 - top, max(below, 0.002), hi


# --------------------------------------------------------------------------
# 7. Opponent stats, counted from the histories we are shown
# --------------------------------------------------------------------------

class _Seat:
    __slots__ = ("stab", "cont", "raise_", "recent", "hu")

    def __init__(self):
        self.stab = [0, 0]                       # [bets, chances] when checked to
        self.cont = [[0, 0], [0, 0], [0, 0], [0, 0]]   # [continued, faced] by size bucket
        self.raise_ = [0, 0]                     # [raised, faced a bet]
        self.recent = deque(maxlen=PARAMS["dead_window"])   # (passive, facing a bet)
        self.hu = deque(maxlen=24)               # did we fold to their heads-up bet


def shrink(successes, trials, prior_mean, prior_weight):
    return (successes + prior_mean * prior_weight) / (trials + prior_weight)


class _Table:
    """Everything remembered for one of our seats during a round."""

    def __init__(self, n):
        self.n = n
        self.seats = [_Seat() for _ in range(n)]
        self.hand = None
        self.reset_hand()

    def reset_hand(self):
        self.done = 0                # history entries already processed
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

    # -- stats, shrunk -------------------------------------------------------
    def _pooled(self, pick, seat, default):
        s = t = 0
        for j, q in enumerate(self.seats):
            if j != seat:
                a = pick(q)
                s += a[0]
                t += a[1]
        return shrink(s, t, default, PARAMS["prior_weight_post"])

    def stat(self, seat, name, prof, bucket=1):
        """stab, cont (by bucket), cont_raise or raise for a seat."""
        p = PARAMS
        prior = p["prior"]
        q = self.seats[seat]
        if name == "stab":
            default = min(0.9, max(0.05, prior["stab"] * prof["aggression"] / 0.40))
            a = q.stab
            mean = self._pooled(lambda z: z.stab, seat, default)
        elif name == "raise":
            default = min(0.5, max(0.01, prior["raise"] * prof["aggression"] / 0.40))
            a = q.raise_
            mean = self._pooled(lambda z: z.raise_, seat, default)
        else:
            if not p["use_size_buckets"]:
                bucket = 1
            base = prior["cont_raise"] if name == "cont_raise" else prior["cont"][bucket]
            default = min(0.97, max(0.03, base * (1.0 - prof["fold_to_bet"]) / 0.55))
            if name == "cont_raise":
                return default
            a = q.cont[bucket]
            mean = self._pooled(lambda z: z.cont[bucket], seat, default)
        return shrink(a[0], a[1], mean, p["prior_weight_post"])

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


def _profiles(profiles, seats, hero):
    """Contract profiles with preflop stats shrunk toward the table average."""
    prior = PARAMS["prior"]
    pw = PARAMS["prior_weight_pre"]
    raw = {}
    for s in range(seats):
        q = profiles.get(s) if isinstance(profiles, dict) else None
        if not isinstance(q, dict):
            q = {}
        hands = q.get("hands") or 0
        d = {"hands": hands if isinstance(hands, (int, float)) else 0}
        for k, default in (("pfr", prior["pfr"]), ("vpip", prior["vpip"]), ("three_bet", prior["three_bet"]),
                           ("aggression", 0.40), ("fold_to_bet", 0.45)):
            x = q.get(k)
            d[k] = float(x) if isinstance(x, (int, float)) and 0.0 <= x <= 1.0 else default
        raw[s] = d
    out = {}
    for s in range(seats):
        if s == hero:
            continue
        d = raw[s]
        o = {"aggression": d["aggression"], "fold_to_bet": d["fold_to_bet"]}
        for k in ("pfr", "vpip", "three_bet"):
            succ = trials = 0.0
            for j in range(seats):
                if j != s and j != hero:
                    succ += raw[j][k] * raw[j]["hands"]
                    trials += raw[j]["hands"]
            mean = shrink(succ, trials, prior[k], pw)
            o[k] = shrink(d[k] * d["hands"], d["hands"], mean, pw)
        out[s] = o
    return out


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


def _advance(tb, state, profs, hero_ids, t0):
    """Process history entries not seen yet: replay the pot, count each
    opponent's actions, and update the ranges of opponents still in."""
    p = PARAMS
    hero = state["seat"]
    history = state["history"]
    board = state["board"]
    folded = state["folded"]
    seats = tb.seats
    bluffs = p["bluff"]
    limit = t0 + p["update_ms"] / 1000.0
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

        if tb.ranges is None:
            _seed(tb, state, profs, hero_ids)
        facing = tb.high > mine
        bucket_faced = _bucket(tb.frac)
        like = None
        q = seats[seat]
        if action == "raise":
            frac = (amount - tb.high) / float(max(1, tb.pot + tb.high - mine))
            b = _bucket(frac) if p["use_size_buckets"] else 1
            if seat != hero:
                prof = profs[seat]
                if facing:
                    like = _aggr(tb.stat(seat, "raise", prof), bluffs[b])
                    q.cont[bucket_faced][0] += 1
                    q.cont[bucket_faced][1] += 1
                    q.raise_[0] += 1
                    q.raise_[1] += 1
                else:
                    like = _aggr(tb.stat(seat, "stab", prof), bluffs[b])
                    q.stab[0] += 1
                    q.stab[1] += 1
                q.recent.append((False, facing))
            tb.pot += amount - mine
            bets[seat] = tb.high = amount
            tb.frac = frac
            tb.aggressor[street] = seat
        elif action == "call":
            if seat != hero:
                prof = profs[seat]
                cont = tb.stat(seat, "cont", prof, bucket_faced)
                rf = tb.stat(seat, "raise", prof)
                like = (1.0 - cont, p["call_below_like"], 1.0, 1.0 - min(rf, cont * 0.8), p["call_raise_like"])
                q.cont[bucket_faced][0] += 1
                q.cont[bucket_faced][1] += 1
                q.raise_[1] += 1
                q.recent.append((False, True))
            tb.pot += amount
            bets[seat] = mine + amount
        elif action == "check":
            if seat != hero:
                if _CLOCK() < limit:
                    t, lo, hi = _aggr(tb.stat(seat, "stab", profs[seat]), bluffs[1])
                    like = (t, 1.0 - lo, 1.0 - hi)
                else:
                    STATS["skipped_updates"] += 1
                q.stab[1] += 1
                q.recent.append((True, False))
        elif action == "fold":
            if seat != hero and facing:
                q.cont[bucket_faced][1] += 1
                q.raise_[1] += 1
                q.recent.append((True, True))
        tb.acted.add(seat)

        if like is not None and not folded[seat]:
            rg = tb.ranges.get(seat)
            if rg is not None:
                if rg.street != street:
                    st = tb.streets.get(street)
                    if st is None:
                        st = tb.streets[street] = _street([_ID[c] for c in board[:_BOARD_LEN[street]]])
                    rg.enter(street, st)
                rg.apply(*like)
    tb.done = len(history)


# --------------------------------------------------------------------------
# 3. One set of trials
# --------------------------------------------------------------------------

def _schedule(bands, scale):
    """Band index per trial, interleaved so that stopping early keeps the mix."""
    slots = []
    for b, (_, _, n) in enumerate(bands):
        n = max(2, int(n * scale + 0.5))
        slots += [((k + 0.5) / n, b) for k in range(n)]
    slots.sort()
    return [b for _, b in slots]


class _Trials:
    """n trials. For trial t: w[t] its weight, s[t] each opponent's percentile
    in their own range (main opponent first), r[t] whether hero is ahead (1),
    tied (0) or behind (-1) against each at showdown, u[t] a random number
    reused across bet sizes."""
    __slots__ = ("n", "w", "s", "r", "u")


def _make_trials(hero_ids, ids, st, ranges, deadline):
    p = PARAMS
    bands = p["bands"]
    sched = _schedule(bands, _SCALE * p["trials"] / 200.0)
    rnd = _RNG.random
    clock = _CLOCK
    prim = ranges[0]
    others = ranges[1:]
    mem0, cum0, tot0 = prim.mem, prim.cum, prim.total
    last0 = len(mem0) - 1
    need = 5 - len(ids)
    c1s, c2s, cks, css = _C1, _C2, _CK, _CS
    nf, fv, flush, k5, s8 = _NF, _FV, _FLUSH, _K5, _S8
    val = st.val
    h1, h2 = hero_ids
    hidx = _CIDX[(h1, h2) if h1 < h2 else (h2, h1)]
    hv = val[hidx]
    bk = bs = 0
    bsm = [0, 0, 0, 0]
    taken = set(hero_ids)
    for c in ids:
        bk += k5[c]
        bs += s8[c]
        bsm[c & 3] |= 1 << (c >> 2)
        taken.add(c)
    deck = [c for c in range(52) if c not in taken]
    nd = len(deck)
    T = _Trials()
    tb_, ts, tr, tu = [], [], [], []
    per_band = [0] * len(bands)
    for t, b in enumerate(sched):
        if not t & 15 and clock() > deadline:
            break
        lo, hi, _ = bands[b]
        u = lo + (hi - lo) * rnd()
        k = bisect_right(cum0, u * tot0)
        i0 = mem0[k if k < last0 else last0]
        idxs = [i0]
        ss = [u]
        used = {c1s[i0], c2s[i0]}
        ok = True
        for rg in others:
            mem, cum, tot = rg.mem, rg.cum, rg.total
            last = len(mem) - 1
            for _ in (0, 1, 2, 3):
                uj = rnd()
                k = bisect_right(cum, uj * tot)
                ij = mem[k if k < last else last]
                a = c1s[ij]
                c = c2s[ij]
                if a in used or c in used:
                    continue
                used.add(a)
                used.add(c)
                idxs.append(ij)
                ss.append(uj)
                break
            else:
                ok = False
                break
        if not ok:
            continue
        if need == 0:
            res = [1 if hv > val[i] else 0 if hv == val[i] else -1 for i in idxs]
        else:
            x = deck[int(rnd() * nd)]
            while x in used:
                x = deck[int(rnd() * nd)]
            rk = bk + k5[x]
            rs = bs + s8[x]
            y = -1
            if need == 2:
                y = deck[int(rnd() * nd)]
                while y in used or y == x:
                    y = deck[int(rnd() * nd)]
                rk += k5[y]
                rs += s8[y]
            hv = nf[rk + cks[hidx]]
            f = flush[rs + css[hidx]]
            if f >= 0:
                hv = _with_flush(hv, f, bsm[f], x, y, h1, h2)
            res = []
            for i in idxs:
                v = nf[rk + cks[i]]
                f = flush[rs + css[i]]
                if f >= 0:
                    v = _with_flush(v, f, bsm[f], x, y, c1s[i], c2s[i])
                res.append(1 if hv > v else 0 if hv == v else -1)
        per_band[b] += 1
        tb_.append(b)
        ts.append(ss)
        tr.append(res)
        tu.append(rnd())
    mass = [(hi - lo) / per_band[b] if per_band[b] else 0.0 for b, (lo, hi, _) in enumerate(bands)]
    T.n = len(tb_)
    T.w = [mass[b] for b in tb_]
    T.s, T.r, T.u = ts, tr, tu
    return T


def _with_flush(v, f, m, x, y, c1, c2):
    for c in (x, y, c1, c2):
        if c >= 0 and c & 3 == f:
            m |= 1 << (c >> 2)
    fvv = _FV[m]
    return fvv if fvv > v else v


def _share(res):
    """Hero's share of the pot at showdown against these opponents."""
    if -1 in res:
        return 0.0
    return 1.0 / (1 + res.count(0))


def equity(T, lo=None):
    """Showdown share against all live opponents; with `lo`, only against the
    main opponent's hands at or above that percentile."""
    num = den = 0.0
    w, s, r = T.w, T.s, T.r
    for t in range(T.n):
        if lo is not None and s[t][0] < lo:
            continue
        x = w[t]
        den += x
        if -1 not in r[t]:
            num += x / (1 + r[t].count(0))
    return num / den if den > 0.0 else None


def ev_bet(T, pot, cost, adds, conts, raise_top=0.0, strong=True):
    """Expected chips from putting `cost` more in, against opponents who each
    continue with the top conts[j] of their range and then add adds[j].
    Every caller's chips are counted. Heads-up, raise_top is the share of the
    opponent's range that raises: when hero is not strong, those trials lose
    the bet. Returns (ev, equity when called, chance of being called)."""
    w, s, r = T.w, T.s, T.r
    cuts = [1.0 - c for c in conts]
    n = len(cuts)
    rng = range(n)
    raise_cut = 1.0 - raise_top
    ev = wsum = cw = cs = 0.0
    for t in range(T.n):
        x = w[t]
        wsum += x
        st = s[t]
        rt = r[t]
        extra = 0
        ties = 0
        behind = False
        called = False
        for j in rng:
            if st[j] >= cuts[j]:
                called = True
                extra += adds[j]
                o = rt[j]
                if o < 0:
                    behind = True
                elif o == 0:
                    ties += 1
        if not called:
            ev += x * pot
            continue
        if raise_top and not strong and st[0] >= raise_cut:
            ev -= x * cost
            continue
        cw += x
        if not behind:
            sh = 1.0 / (1 + ties)
            cs += x * sh
            ev += x * (sh * (pot + cost + extra) - cost)
        else:
            ev -= x * cost
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
    w, s, r, u = T.w, T.s, T.r, T.u
    wsum = bw = bs_ = cs = 0.0
    for t in range(T.n):
        x = w[t]
        wsum += x
        o = r[t][0]
        sh = 1.0 if o > 0 else 0.5 if o == 0 else 0.0
        if u[t] < (hi if s[t][0] >= thr else lo):
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


def required_equity(price, streets_left, oop, behind, stack_share, structural=True):
    """Equity needed to call. `price` is to_call / (pot + to_call)."""
    if not structural:
        return price
    p = PARAMS
    return (price + p["margin_street"] * streets_left + (p["margin_oop"] if oop else 0.0)
            + p["margin_behind"] * behind + p["margin_stack"] * stack_share)


def choose_no_bet(state, T, tb, opps, profs, eq, strong, closing, in_position, streets_left):
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
    realize = p["realize_last"] if in_position else p["realize_not_last"]
    stab = None
    if hu and not closing:
        stab = _aggr(tb.stat(opps[0], "stab", profs[opps[0]]), p["bluff"][1])
    base = ev_check(T, pot, eq, closing, stab, 0.0 if closing and not streets_left else realize)
    sizes = list(p["sizes"])
    if stack <= p["allin_spr"] * pot:
        sizes.append(None)
    best = None
    best_ev = base
    best_value = False
    for target in dict.fromkeys(_raise_to(state, f) for f in sizes):
        cost = target - my_bet
        if cost <= 0:
            continue
        b = _bucket(cost / float(max(pot, 1)))
        conts = [tb.stat(j, "cont", profs[j], b) for j in opps]
        rt = tb.stat(opps[0], "raise", profs[opps[0]]) if hu and p["use_raise_risk"] else 0.0
        ev, eq_called, _ = ev_bet(T, pot, cost, [cost] * n, conts, rt, strong)
        gain = ev - base
        value = eq_called is not None and eq_called >= 0.5
        if cost >= p["commit_frac"] * stack and not value:
            continue
        if value:
            if gain <= p["value_gain"] * pot * n:
                continue
        else:
            if not (p["use_bluffs"] and hu and tb.faced(opps[0]) >= p["bluff_min_seen"]
                    and gain > p["bluff_gain"] * pot):
                continue
        if ev > best_ev:
            best, best_ev, best_value = target, ev, value
    if best is None:
        return passive
    if not best_value:
        freq = min(p["bluff_max_freq"], (best_ev - base) / (p["bluff_full"] * max(pot, 1)))
        if _RNG.random() >= freq:
            return passive
    return {"action": "raise", "amount": best}


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
    need = required_equity(price, streets_left, not in_position, behind,
                           min(1.0, to_call / float(max(stack, 1))), structural)
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

    ids = [_ID[c] for c in board]
    hero_ids = [_ID[c] for c in state["hole_cards"]]
    st = tb.streets.get(street)
    if st is None:
        st = tb.streets[street] = _street(ids)
    h1, h2 = hero_ids
    out["seff"] = seff = st.seff[_CIDX[(h1, h2) if h1 < h2 else (h2, h1)]]

    profs = _profiles(profiles, n, seat)
    _advance(tb, state, profs, hero_ids, t0)
    if tb.ranges is None:
        _seed(tb, state, profs, hero_ids)
    opps = [s for s in range(n) if not folded[s] and s != seat]
    out["opps"] = len(opps)
    if not opps:
        return passive
    to_call = state["to_call"]

    # Dead bots: minimum bet every time nobody has bet.
    if p["use_dead_bot"] and to_call <= 0 and "raise" in legal and all(tb.dead(j) for j in opps):
        return {"action": "raise", "amount": state["min_raise_to"]}

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
                    rg.w[i] = 0.0
        if rg.street != street:
            rg.enter(street, st)
        rg.ready()
        if rg.total <= 0.0 or not rg.mem:
            # Everything was ruled out: start that seat again from any two cards.
            rg.w = [0.0 if (_C1[i] in hero_ids or _C2[i] in hero_ids) else 1.0 for i in range(_NC)]
            rg.enter(street, st)
            rg.ready()
        ranges.append(rg)

    T = _make_trials(hero_ids, ids, st, ranges, t0 + p["deadline_ms"] / 1000.0)
    out["trials"] = T.n
    if T.n < p["min_trials"] * _SCALE * p["trials"] / 200.0:
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
        return choose_no_bet(state, T, tb, opps, profs, eq, strong, behind == 0, in_position, streets_left)
    bets = state["bets"]
    high = max(bets)
    behind = sum(1 for j in opps if j != bettor and bets[j] < high and stacks[j] > 0)
    combo = street != "river" and seff >= p["floor_combo"][0 if street == "flop" else 1] \
        and _is_combo_draw(hero_ids, ids)
    return choose_facing_bet(state, T, tb, opps, profs, eq, bettor, behind, in_position, streets_left, combo)


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
