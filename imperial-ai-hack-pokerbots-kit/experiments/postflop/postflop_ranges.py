"""Postflop strategy "ranges": opponent ranges, sampled equity and exploit hooks.

The design is tools/postflop/STRATEGY.md on the feat/postflop-lab branch.
Experimental: not imported by src/postflop.py and not bundled by build.py.
Pipeline, numbered as in STRATEGY.md:
  1 Ranges    each live opponent has a preflop range picked by their preflop
              action class (open, 3-bet, call, limp, check). Postflop actions
              reweight it by the hand's strength class on the board at the time
              of the action. The weights are applied as hands are drawn for a
              trial (accept or redraw), so only sampled hands are classified.
  2 Equity    heads-up on the river: every combination in the range. Otherwise
              sampled trials. Both stop at a time budget.
  3 Features  made-hand class, draws, board texture, stack-to-pot ratio,
              opponents left, position, betting lead.
  4-6         value bet / size by estimated chip gain / call / raise / stack-off.
  7 Hooks     station, over-folder, maniac, passive-bets-big, dead bot. Each has
              a switch and a cap in PARAMS.
  8 Fallback  made-hand class by size of bet faced, on any error or when the
              equity estimate got too few trials in before its time budget.

Every decision follows at least one opponent action, which is a range update,
so there is no equity cache: it would never be hit.
"""
import random
import time

from . import handeval

PARAMS = {
    # equity
    "trials_hu": 300, "trials_multi": 300,   # targets; the budget usually stops it first
    "budget_ms": 0.8,                        # equity loop stops this long after decide() starts
    "min_trials": 12,                        # fewer than this and the fallback table decides
    "weight_floor": 0.2,                     # below this a trial survives with probability weight/floor
    # range reweighting: multipliers by class (air, weak pair, top pair/overpair, two pair+, strong draw)
    "bluff_prior": 0.30, "bluff_per_aggression": 0.5,
    "w_bet": (None, 0.6, 1.25, 1.6, 1.2),    # None = that opponent's bluff rate
    "w_raise": (None, 0.3, 0.9, 2.2, 1.0),   # None = half the bluff rate
    "w_check": (1.0, 1.15, 0.95, 0.7, 1.0),
    "w_call": (0.35, 1.1, 1.25, 0.9, 1.2),
    # chance each class continues against our bet / our raise, at fold_to_bet 0.45
    "p_call": (0.12, 0.5, 0.9, 1.0, 0.8),
    "p_call_raise": (0.03, 0.15, 0.6, 1.0, 0.5),
    # not facing a bet
    "value_hu": 0.50, "value_two": 0.60, "value_many": 0.70,
    "sizes": (0.33, 0.66, 1.0),              # of the pot; all-in is added when allin_spr allows
    "allin_spr": 2.5,
    "size_cont_base": 1.25, "size_cont_slope": 0.45,   # continue chance scales with bet size
    "call_tighten": 0.10,                    # equity against callers lost per pot-size of extra bet
    "cbet_freq": 0.65, "cbet_size": 0.33,
    "semibluff_freq": 0.8, "semibluff_size": 0.66,
    # facing a bet
    "margin_hu": 0.03, "margin_multi": 0.08, "margin_per_street": 0.015, "margin_oop": 0.02,
    "raise_value": 0.70, "raise_size": 0.75,
    "combo_raise_freq": 0.15,
    "fold_pair_to_late_raise": True,
    # stack-off
    "stackoff": 0.55, "commit_frac": 0.5,
    # exploit hooks: switch, then cap on how far it moves a threshold
    "min_hands": 30,
    "hook_station": True, "station_thin": 0.05, "station_fold_to_bet": 0.25, "station_allin_spr": 4.0,
    "hook_overfolder": True, "overfold_fold_to_bet": 0.60, "overfold_cbet_add": 0.25,
    "overfold_river_bluff": 0.40,
    "hook_maniac": True, "maniac_aggression": 0.70, "maniac_margin": 0.06, "maniac_slowplay": 0.5,
    "hook_passive_big": True, "passive_aggression": 0.20, "passive_big_bet": 0.75, "passive_margin": 0.08,
    "hook_dead": True, "dead_hands": 40,
    # set True to let exceptions out (for testing); normally they become the fallback action
    "raise_errors": False,
}

_DEFAULTS = {"hands": 0, "vpip": 0.30, "pfr": 0.15, "three_bet": 0.05, "aggression": 0.40,
             "fold_to_bet": 0.45, "style": "unknown"}
_RNG = random.Random(20261114)
_CARDS = [r + s for r in "23456789TJQKA" for s in "cdhs"]   # id = rank * 4 + suit
_ID = {c: i for i, c in enumerate(_CARDS)}
AIR, WEAK, GOOD, STRONG, DRAW = 0, 1, 2, 3, 4
_HERO_CLASS = {"two_pair": 3, "set": 3, "trips": 3, "straight": 3, "flush": 3, "full_house": 3,
               "quads": 3, "straight_flush": 3, "overpair": 2, "top_pair": 2, "middle_pair": 1,
               "underpair": 1, "bottom_pair": 1, "pair_and_board_pair": 1}
_SIX = (0, 1, 2, 3, 4, 5)
_STREETS_LEFT = {"flop": 2, "turn": 1, "river": 0}
_BOARD_LEN = {"flop": 3, "turn": 4, "river": 5}
# Fallback: rows are our made class 0-3, columns are no bet / small / medium / big bet.
# "b" bet two thirds of the pot, "r" raise, "c" call, "x" check or fold.
_FALLBACK = ("xxxx", "xcxx", "bccx", "brrc")


def _build_straights():
    """13-bit rank mask -> (is a straight, ranks that would complete one)."""
    made = bytearray(8192)
    for mask in range(8192):
        m = (mask << 1) | (mask >> 12 & 1)
        for low in range(10):
            if (m >> low) & 31 == 31:
                made[mask] = 1
                break
    outs = bytearray(8192)
    for mask in range(8192):
        if not made[mask]:
            outs[mask] = sum(1 for r in range(13) if not mask >> r & 1 and made[mask | 1 << r])
    return made, outs


def _build_order():
    """All 1326 combinations as (card, card), strongest preflop hands first."""
    out = []
    for c1 in range(52):
        for c2 in range(c1 + 1, 52):
            hi, lo = c2 >> 2, c1 >> 2
            if hi == lo:
                score = 14 + 2.2 * hi
            else:
                gap = hi - lo
                score = 1.6 * hi + 0.9 * lo + (3 if (c1 ^ c2) & 3 == 0 else 0) + max(0, 3 - gap)
            out.append((-score, c1, c2))
    out.sort()
    return [(c1, c2) for _, c1, c2 in out]


_MADE, _OUTS = _build_straights()
_ORDER = _build_order()
_pools = {}


def _pool(cls, prof):
    """Preflop range for an action class as a list of (card, card, weight)."""
    def step(x):
        return int(x * 20 + 0.5)

    p, v, t = step(prof["pfr"]), step(prof["vpip"]), step(prof["three_bet"] * 2)
    key = (cls, p, v, t)
    pool = _pools.get(key)
    if pool is None:
        p = min(0.6, max(0.10, p / 20.0))
        v = min(0.9, max(0.15, v / 20.0))
        t = min(0.3, max(0.03, t / 40.0))
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
        pool = []
        for lo, hi, w in segs:
            pool += [(c1, c2, w) for c1, c2 in _ORDER[int(lo * 1326):int(min(hi, 1.0) * 1326)]]
        _pools[key] = pool
    return pool


for _c in ("3bet", "open", "call", "limp", "check"):
    _pool(_c, _DEFAULTS)


def _board_info(ids, last):
    counts = [0] * 13
    suits = [0, 0, 0, 0]
    mask = 0
    for c in ids:
        counts[c >> 2] += 1
        suits[c & 3] += 1
        mask |= 1 << (c >> 2)
    return counts, mask.bit_length() - 1, mask, suits, last


def _classify(c1, c2, info):
    """Strength class of an opponent hand on a board. About 1 microsecond."""
    counts, top, bmask, suits, last = info
    a = c1 >> 2
    b = c2 >> 2
    s1 = c1 & 3
    s2 = c2 & 3
    if s1 == s2:
        n = suits[s1] + 2
    else:
        n = suits[s1] if suits[s1] > suits[s2] else suits[s2]
        n += 1
    if n >= 5:
        return 3
    m = bmask | 1 << a | 1 << b
    if _MADE[m] and not _MADE[bmask]:
        return 3
    if a == b:
        if counts[a]:
            return 3
        made = 2 if a > top else 1
    else:
        ha = counts[a]
        hb = counts[b]
        if (ha and hb) or ha > 1 or hb > 1:
            return 3
        if ha:
            made = 2 if a == top else 1
        elif hb:
            made = 2 if b == top else 1
        else:
            made = 0
    if made == 2 or last:
        return made
    if n == 4 or _OUTS[m] >= 2:
        return 4
    return made


def _profile(profiles, seat):
    """Profile with defaults filled in; numbers are trusted only after min_hands."""
    raw = profiles.get(seat) if profiles else None
    if not isinstance(raw, dict):
        return dict(_DEFAULTS, trusted=False)
    trusted = (raw.get("hands") or 0) >= PARAMS["min_hands"]
    out = {"trusted": trusted, "hands": raw.get("hands") or 0, "style": raw.get("style") or "unknown"}
    for k in ("vpip", "pfr", "three_bet", "aggression", "fold_to_bet"):
        x = raw.get(k)
        out[k] = float(x) if trusted and isinstance(x, (int, float)) else _DEFAULTS[k]
    return out


def _read_history(history):
    """Preflop action class per seat, postflop action codes per seat and street
    (0 bet, 1 raise, 2 check, 3 call), and the last aggressor of each street."""
    pre, post, aggressor = {}, {}, {}
    raises = 0
    raised = set()
    for h in history:
        seat, street, action = h["seat"], h["street"], h["action"]
        if street == "preflop":
            if action == "raise":
                pre[seat] = "3bet" if raises else "open"
                raises += 1
                aggressor[street] = seat
            elif action == "call":
                if pre.get(seat) not in ("open", "3bet"):
                    pre[seat] = "call" if raises else "limp"
            elif action == "check":
                pre.setdefault(seat, "check")
            continue
        if action == "raise":
            code = 1 if street in raised else 0
            raised.add(street)
            aggressor[street] = seat
        elif action == "check":
            code = 2
        elif action == "call":
            code = 3
        else:
            continue
        post.setdefault(seat, {}).setdefault(street, []).append(code)
    return pre, post, aggressor


def _opponent(seat, prof, pre, post, infos, street, facing):
    """Everything the equity loop needs for one opponent."""
    p = PARAMS
    bluff = p["bluff_prior"] + (prof["aggression"] - _DEFAULTS["aggression"]) * p["bluff_per_aggression"]
    bluff += {"maniac": 0.25, "loose_aggressive": 0.10, "tight_passive": -0.10,
              "loose_passive": -0.10}.get(prof["style"], 0.0)
    bluff = min(0.8, max(0.05, bluff))
    tables = (p["w_bet"], p["w_raise"], p["w_check"], p["w_call"])
    earlier, current = [], None
    for st, codes in post.get(seat, {}).items():
        mult = [1.0] * 5
        for code in codes:
            t = tables[code]
            for k in range(5):
                x = t[k]
                mult[k] *= (bluff if code == 0 else bluff * 0.5) if x is None else x
        if st == street:
            current = mult
        else:
            earlier.append((infos[st], mult))
    # How often each class continues against us, scaled by this seat's fold rate.
    scale = prof["fold_to_bet"] / _DEFAULTS["fold_to_bet"]
    base = p["p_call_raise"] if facing else p["p_call"]
    cont = [max(0.0, 1.0 - (1.0 - x) * scale) for x in base]
    pool = _pool(pre.get(seat, "check"), prof)
    top = max(current) if current else 1.0
    for _, mult in earlier:
        top *= max(mult)
    return pool, len(pool), earlier, current, cont, 1.0 / top


def _equity(hole, board, opps, info, deadline, facing):
    """Returns (weight, wins) three times over: against the weighted ranges,
    against the hands that continue if we bet or raise, and against those of
    them that are two pair or better; then the number of trials. Wins count a
    tie as half. When we are not facing a bet only the hands that continue are
    played out, so the first pair's wins are the same as the second's."""
    p = PARAMS
    rank = handeval.rank
    clock = time.perf_counter
    classify = _classify
    cards = _CARDS
    hs = tuple(hole)
    bs = tuple(board)
    dead = {_ID[c] for c in hole}
    dead.update(_ID[c] for c in board)
    need = 5 - len(board)
    sw = se = swc = sec = sws = ses = 0.0
    done = 0

    if need == 0 and len(opps) == 1:
        # Heads-up on the river: every combination, in a scattered order so that
        # stopping at the deadline leaves an even sample of the range.
        hr = rank(hs + bs)
        pool, n, earlier, current, cont, _ = opps[0]
        step = 211 if n % 211 else 223
        i = 0
        for j in range(n):
            if not j & 31 and clock() > deadline:
                break
            c1, c2, w = pool[i]
            i = (i + step) % n
            if c1 in dead or c2 in dead:
                continue
            for binfo, mult in earlier:
                w *= mult[classify(c1, c2, binfo)]
            k = classify(c1, c2, info)
            if current:
                w *= current[k]
            if w < 1e-4:
                continue
            r = rank((cards[c1], cards[c2]) + bs)
            v = 1.0 if hr > r else 0.5 if hr == r else 0.0
            done += 1
            sw += w
            se += w * v
            wc = w * cont[k]
            swc += wc
            sec += wc * v
            if k == 3:
                sws += wc
                ses += wc * v
        return sw, se, swc, sec, sws, ses, done

    rnd = _RNG.random
    deck = [c for c in range(52) if c not in dead]
    nd = len(deck)
    floor = p["weight_floor"]
    target = p["trials_hu"] if len(opps) == 1 else p["trials_multi"]
    full = bs
    hr = rank(hs + bs) if need == 0 else None
    tries = 0
    while done < target:
        tries += 1
        if not tries & 15 and (clock() > deadline or tries > 4000):
            break
        w = 1.0
        callers = 0
        used = set()
        hands = []
        for pool, n, earlier, current, cont, inv in opps:
            # Draw this opponent's hand from their reweighted range: accept a
            # draw with probability weight / largest possible weight. If none
            # of six draws is accepted, keep the last and carry its weight.
            x = 0.0
            for _ in _SIX:
                c1, c2, x = pool[int(rnd() * n)]
                if c1 in dead or c2 in dead or c1 in used or c2 in used:
                    x = 0.0
                    continue
                for binfo, mult in earlier:
                    x *= mult[classify(c1, c2, binfo)]
                k = classify(c1, c2, info)
                if current:
                    x *= current[k]
                x *= inv
                if rnd() < x:
                    x = 1.0
                    break
            if x <= 0.0:
                w = 0.0
                break
            w *= x
            used.add(c1)
            used.add(c2)
            # Does this hand continue against our bet or raise?
            if rnd() < cont[k]:
                callers += 1
                hands.append((cards[c1], cards[c2], k))
            elif facing:
                hands.append((cards[c1], cards[c2], -1))
        if w <= 0.0:
            continue
        if w < floor:
            if rnd() * floor > w:
                continue
            w = floor
        done += 1
        sw += w
        if not hands:
            continue
        if need:
            x = deck[int(rnd() * nd)]
            while x in used:
                x = deck[int(rnd() * nd)]
            if need == 2:
                y = deck[int(rnd() * nd)]
                while y in used or y == x:
                    y = deck[int(rnd() * nd)]
                full = bs + (cards[x], cards[y])
            else:
                full = bs + (cards[x],)
            hr = rank(hs + full)
        # 2 = we beat everyone in the group, 1 = tie for best, 0 = beaten.
        v_all = v_call = v_strong = 2
        strong = False
        for a, b, k in hands:
            r = rank((a, b) + full)
            v = 2 if hr > r else 1 if hr == r else 0
            if v < v_all:
                v_all = v
            if k >= 0:
                if v < v_call:
                    v_call = v
                if k == 3:
                    strong = True
                    if v < v_strong:
                        v_strong = v
        se += w * v_all * 0.5
        if callers:
            swc += w
            sec += w * v_call * 0.5
            if strong:
                sws += w
                ses += w * v_strong * 0.5
    return sw, se, swc, sec, sws, ses, done


def _raise_to(state, fraction):
    """Raise-to amount for a bet of `fraction` of the pot after calling; None is the maximum."""
    lo, hi = state["min_raise_to"], state["max_raise_to"]
    if fraction is None:
        return hi
    target = max(state["bets"]) + int(fraction * (state["pot"] + state["to_call"]))
    return max(lo, min(hi, target))


def _fallback(state):
    """Step 8: made-hand class by size of bet faced. No sampling, no profiles."""
    legal = state.get("legal_actions", ())
    passive = {"action": "check" if "check" in legal else "fold"}
    try:
        d = handeval.describe(state["hole_cards"], state["board"])
        cls = _HERO_CLASS.get(d["made"], 0)
        to_call = state["to_call"]
        if to_call <= 0:
            col = 0
        else:
            price = to_call / float(state["pot"] + to_call)
            col = 1 if price <= 0.22 else 2 if price <= 0.30 else 3
        code = _FALLBACK[cls][col]
        if code == "x" and col == 1 and (d["flush_draw"] or d["straight_draw"] == "open_ended"):
            code = "c"
        if code in "br" and "raise" in legal:
            return {"action": "raise", "amount": _raise_to(state, 0.66)}
        if code != "x" and "call" in legal:
            return {"action": "call"}
    except Exception:
        pass
    return passive


def _decide(state, profiles):
    t0 = time.perf_counter()
    p = PARAMS
    legal = state["legal_actions"]
    seat = state["seat"]
    street = state["street"]
    board = state["board"]
    hole = state["hole_cards"]
    pot = state["pot"]
    to_call = state["to_call"]
    folded = state["folded"]
    can_raise = "raise" in legal
    passive = {"action": "check" if "check" in legal else "fold"}
    live = [s for s in range(len(folded)) if not folded[s] and s != seat]
    if not live or len(board) < 3:
        return passive

    # 3. Features.
    d = handeval.describe(hole, board)
    made = _HERO_CLASS.get(d["made"], 0)
    flush_draw = d["flush_draw"]
    straight_draw = d["straight_draw"]
    strong_draw = flush_draw or straight_draw == "open_ended"
    combo_draw = flush_draw and straight_draw != "none"
    ids = [_ID[c] for c in board]
    info = _board_info(ids, len(ids) == 5)
    counts, _, bmask, suits, _ = info
    ranks = [r for r in range(13) if counts[r]]
    monotone = max(suits) >= 3
    connected = any(ranks[i + 2] - ranks[i] <= 4 for i in range(len(ranks) - 2))
    dry = not monotone and not connected
    stack = state["stacks"][seat]
    spr = stack / float(max(pot, 1))
    n_opp = len(live)
    hu = n_opp == 1
    n_seats = len(folded)
    button = state["button"]
    my_pos = (seat - button - 1) % n_seats
    in_position = all((s - button - 1) % n_seats < my_pos for s in live)
    streets_left = _STREETS_LEFT[street]

    pre, post, aggressor = _read_history(state["history"])
    lead = street not in aggressor
    if lead:
        prev = [st for st in ("preflop", "flop", "turn") if st in aggressor and st != street]
        lead = bool(prev) and aggressor[prev[-1]] == seat

    # 7. Exploit hooks read the profiles of the opponents still in.
    profs = {s: _profile(profiles, s) for s in live}
    station = overfolder = maniac = dead = False
    if p["hook_dead"]:
        dead = all(q["hands"] >= p["dead_hands"] and q["pfr"] <= 0.02 and q["aggression"] <= 0.02
                   and q["fold_to_bet"] >= 0.95 for q in profs.values())
    if dead and to_call == 0 and can_raise:
        return {"action": "raise", "amount": state["min_raise_to"]}
    if p["hook_station"]:
        station = any(q["style"] == "loose_passive" or
                      (q["trusted"] and q["fold_to_bet"] <= p["station_fold_to_bet"]) for q in profs.values())
    if p["hook_overfolder"] and not station:
        overfolder = all(q["trusted"] and q["fold_to_bet"] >= p["overfold_fold_to_bet"] for q in profs.values())
    if p["hook_maniac"]:
        maniac = any(q["style"] == "maniac" or
                     (q["trusted"] and q["aggression"] >= p["maniac_aggression"]) for q in profs.values())

    # 1 and 2. Ranges and equity.
    infos = {}
    for st, n in _BOARD_LEN.items():
        if n < len(ids):
            infos[st] = _board_info(ids[:n], False)
    opps = [_opponent(s, profs[s], pre, post, infos, street, to_call > 0) for s in live]
    sw, se, swc, sec, sws, ses, trials = _equity(
        hole, board, opps, info, t0 + p["budget_ms"] / 1000.0, to_call > 0)
    if sw <= 0.0 or trials < p["min_trials"]:
        return None
    eq = se / sw if to_call > 0 else None           # against the weighted ranges
    eq_cont = sec / swc if swc > 1e-9 else eq       # against hands that continue
    cont_base = swc / sw                            # chance at least one opponent continues
    # 6. Stack-off range: two pair or better, unless the profile says they stack off lighter.
    loose_stack = any(q["style"] in ("maniac", "loose_aggressive") or
                      (q["trusted"] and q["aggression"] >= 0.6) for q in profs.values())
    if sws > 1e-9 and not loose_stack:
        eq_stack = ses / sws
    else:
        eq_stack = eq if eq is not None else eq_cont if eq_cont is not None else 0.0
    stack_ok = eq_stack > p["stackoff"]
    def commits(chips):
        return chips >= p["commit_frac"] * stack

    my_bet = state["bets"][seat]
    rnd = _RNG.random

    if to_call <= 0:
        # 4. Not facing a bet.
        if not can_raise:
            return passive
        if maniac and made == 3 and hu and streets_left and rnd() < p["maniac_slowplay"]:
            return passive
        threshold = p["value_hu"] if hu else p["value_two"] if n_opp == 2 else p["value_many"]
        if station:
            threshold -= p["station_thin"]
        if swc > 1e-9 and eq_cont >= threshold:
            sizes = list(p["sizes"])
            if station:
                sizes = sizes[1:]
            elif overfolder:
                sizes = sizes[:-1]
            if spr <= (p["station_allin_spr"] if station else p["allin_spr"]):
                sizes.append(None)
            best, best_ev = None, None
            for target in dict.fromkeys(_raise_to(state, f) for f in sizes):
                bet = target - my_bet
                frac = bet / float(max(pot, 1))
                if commits(bet):
                    if not stack_ok:
                        continue
                    eq_called = min(eq_cont, eq_stack)
                else:
                    eq_called = eq_cont - p["call_tighten"] * (frac - 0.66)
                cont = cont_base * max(0.3, p["size_cont_base"] - p["size_cont_slope"] * frac)
                cont = min(1.0, max(0.02, cont))
                ev = (1.0 - cont) * pot + cont * (eq_called * (pot + 2 * bet) - bet)
                if best_ev is None or ev > best_ev:
                    best, best_ev = target, ev
            if best is not None:
                return {"action": "raise", "amount": best}
            return passive
        # Bluffs: heads-up only, never into a station.
        if hu and not station:
            freq = p["cbet_freq"] + (p["overfold_cbet_add"] if overfolder else 0.0)
            if lead and dry and (street == "flop" or overfolder) and made <= 1 and rnd() < freq:
                return {"action": "raise", "amount": _raise_to(state, p["cbet_size"])}
            if strong_draw and streets_left and rnd() < p["semibluff_freq"]:
                target = _raise_to(state, p["semibluff_size"])
                if not commits(target - my_bet):
                    return {"action": "raise", "amount": target}
            if overfolder and not streets_left and made == 0 and rnd() < p["overfold_river_bluff"]:
                target = _raise_to(state, p["semibluff_size"])
                if not commits(target - my_bet):
                    return {"action": "raise", "amount": target}
        return passive

    # 5. Facing a bet.
    price = to_call / float(pot + to_call)
    margin = (p["margin_hu"] if hu else p["margin_multi"]) + p["margin_per_street"] * streets_left
    if not in_position:
        margin += p["margin_oop"]
    raises = state.get("raises_this_street") or 1
    bettor = aggressor.get(street)
    if maniac:
        margin -= p["maniac_margin"]
    if p["hook_passive_big"] and bettor in profs:
        q = profs[bettor]
        is_passive = q["style"] in ("tight_passive", "loose_passive") or \
            (q["trusted"] and q["aggression"] <= p["passive_aggression"])
        if is_passive and to_call >= p["passive_big_bet"] * max(pot - to_call, 1):
            margin += p["passive_margin"]

    call_commits = commits(to_call)
    if can_raise and eq_cont >= p["raise_value"] and eq >= price + margin:
        target = _raise_to(state, p["raise_size"])
        if not commits(target - my_bet):
            return {"action": "raise", "amount": target}
        if stack_ok:
            return {"action": "raise", "amount": state["max_raise_to"]}
        # Strong but not strong enough to stack off: fall through to the call rules.
    if p["fold_pair_to_late_raise"] and raises >= 2 and streets_left < 2 and d["category"] == 1 \
            and not maniac:
        return passive
    if call_commits:
        return {"action": "call"} if stack_ok and eq >= price else passive
    if can_raise and hu and combo_draw and streets_left and not station \
            and rnd() < p["combo_raise_freq"]:
        target = _raise_to(state, p["raise_size"])
        if not commits(target - my_bet):
            return {"action": "raise", "amount": target}
    if eq >= price + margin:
        return {"action": "call"}
    if maniac and made >= 2 and raises == 1:
        return {"action": "call"}
    return passive


def decide(state, profiles):
    try:
        action = _decide(state, profiles)
    except Exception:
        if PARAMS["raise_errors"]:
            raise
        action = None
    return action if action is not None else _fallback(state)
