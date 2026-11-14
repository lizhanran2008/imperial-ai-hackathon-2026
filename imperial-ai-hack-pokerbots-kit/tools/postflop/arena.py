"""Compare postflop strategies on the same cards.

    python tools/postflop/arena.py                      # champion + every strategies/*.py
    python tools/postflop/arena.py path/to/mine.py      # just this one against the control
    python tools/postflop/arena.py --rounds 64          # tighter numbers
    python tools/postflop/arena.py --strict             # real 10 ms / 10 s limits, separate process
    python tools/postflop/arena.py --betting pot_limit
    python tools/postflop/arena.py --opponents examples/*.py tools/postflop/strategies/*.py

Every strategy plays the same rounds: same shuffled decks, same seat, same
opponents in the same seats, same preflop. Only the postflop decisions differ,
so the difference against the control is somewhat less noisy than two separate
runs. It is still noisy: against the house bots expect roughly +/-65 bb/100 on
that difference at 200 rounds, so small edges need many rounds.

In --strict mode a stray timeout or two per 20,000 decisions shows up even for
the control, from scheduling jitter on a busy laptop. Compare a candidate's
timeouts with the control's in the same run rather than with zero.

Columns:
  bb/100        big blinds won per 100 hands, the number the leaderboard uses
  vs control    this strategy minus the control, round by round
  verdict       better / worse if the 95% interval of that difference excludes
                zero, otherwise unclear: run more rounds before believing it
  post bb/100   the part of bb/100 won in hands where we saw a flop
  flop%         share of hands where we saw a flop
  ms avg / max  time per decision. Fast mode runs in-process, several tables at
                once, so treat it as a rough guide; --strict is the real check.
  errors        exceptions raised by the strategy (each one became check/fold).
                Counted in fast mode only: in --strict the bundled bot catches
                them itself, so that column shows only a bot that failed to load.
"""
import argparse
import glob
import json
import math
import multiprocessing
import os
import random
import sys
import time

import lab

BIG_BLIND = 20


def _seeded(cls, seed):
    """Agent factory that seeds the bot's own rng, when it has one, so the
    house bots behave the same for every strategy as far as possible."""
    def make():
        agent = cls()
        rng = getattr(agent, "rng", None)
        if isinstance(rng, random.Random):
            rng.seed(seed)
        return agent
    return make


def play_round(task):
    rnd, path, cfg = task
    from engine import FixedHandsTable
    from engine.players import LocalPlayer, SubprocessPlayer

    rng = random.Random(cfg["seed"] * 1000003 + rnd)
    hero = rng.randrange(cfg["seats"])
    lineup = [rng.choice(cfg["opponents"]) for _ in range(cfg["seats"] - 1)]
    table_seed = rng.random()

    players, rest = [], iter(lineup)
    for seat in range(cfg["seats"]):
        if seat != hero:
            cls = lab.agent_class(next(rest), cfg["preflop"])
            players.append(LocalPlayer(_seeded(cls, rnd * 100 + seat)))
        elif cfg["strict"]:
            players.append(SubprocessPlayer(cfg["bundles"][path], timeout_ms=10.0, bank_ms=10000.0))
        else:
            players.append(LocalPlayer(lab.agent_class(path, cfg["preflop"])))

    config = {"betting": cfg["betting"], "raise_cap": cfg["raise_cap"]}
    table = FixedHandsTable(players, hands=cfg["hands"], config=config, seed=table_seed, record=True)
    try:
        res = table.play()
    finally:
        for p in players:
            p.close()

    post_chips = flops = 0
    for rec in res["log"]:
        in_hand = True
        for ev in rec["events"]:
            if ev[0] == "act" and ev[1] == hero and ev[2] == "fold":
                in_hand = False
            elif ev[0] == "board":
                if in_hand:
                    flops += 1
                    post_chips += rec["end"][hero] - rec["stacks"][hero]
                break

    stats = players[hero].stats
    agent = getattr(players[hero], "agent", None)
    return {
        "round": rnd, "path": path, "hands": res["hands"],
        "chips": res["chips"][hero], "post_chips": post_chips, "flops": flops,
        "decisions": stats.decisions, "total_ms": stats.total_ms, "max_ms": stats.max_ms,
        "errors": stats.errors + getattr(agent, "errors", 0),
        "first_error": getattr(agent, "first_error", None) or (stats.error_samples or [None])[0],
        "timeouts": stats.timeouts, "bank_out": stats.bank_out,
    }


def mean_ci(xs):
    n = len(xs)
    m = sum(xs) / n
    if n < 2:
        return m, float("nan")
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m, 1.96 * math.sqrt(var / n)


def main():
    ap = argparse.ArgumentParser(description="Compare postflop strategies on the same cards.")
    ap.add_argument("strategies", nargs="*", help="strategy files (default: champion and strategies/*.py)")
    ap.add_argument("--control", default=lab.CONTROL, help="strategy everything is measured against")
    ap.add_argument("--preflop", default=lab.BASELINE_PREFLOP, help="preflop module used by every strategy")
    ap.add_argument("--opponents", nargs="+", default=None,
                    help="bot or strategy files to fill the other seats (default: examples/*.py)")
    ap.add_argument("--rounds", type=int, default=16)
    ap.add_argument("--hands", type=int, default=1000, help="hands per round (tournament: 1000)")
    ap.add_argument("--seats", type=int, default=8, choices=range(2, 9))
    ap.add_argument("--seed", type=int, default=1, help="same seed, same cards and line-ups")
    ap.add_argument("--betting", choices=["no_limit", "pot_limit", "fixed_limit"], default="no_limit")
    ap.add_argument("--raise-cap", type=int, default=0)
    ap.add_argument("--strict", action="store_true",
                    help="run each strategy as a bundled single file in its own process with the real time limits")
    ap.add_argument("--jobs", type=int, default=None, help="parallel tables (default: all cores, half in --strict)")
    ap.add_argument("--json", default=None, help="also write the full results to this file")
    args = ap.parse_args()

    control = lab.resolve(args.control)
    if args.strategies:
        paths = [lab.resolve(p) for p in args.strategies]
    else:
        paths = [lab.CHAMPION] + sorted(
            p for p in glob.glob(os.path.join(lab.STRATEGIES, "*.py"))
            if not os.path.basename(p).startswith("_"))
    paths = [control] + [p for p in dict.fromkeys(paths) if p != control]
    names = {p: lab.label(p) for p in paths}
    if len(set(names.values())) != len(names):
        sys.exit("Two strategies share a name; rename one: %s" % sorted(names.values()))

    opponents = [lab.resolve(p) for p in args.opponents] if args.opponents else \
        sorted(glob.glob(os.path.join(lab.KIT, "examples", "*.py")))
    opponents = [p for p in opponents if not os.path.basename(p).startswith("_")]
    preflop = lab.resolve(args.preflop)
    for p in paths + opponents:
        lab.agent_class(p, preflop)  # fail now, not inside a worker

    cfg = {"seed": args.seed, "seats": args.seats, "hands": args.hands, "opponents": opponents,
           "preflop": preflop, "betting": args.betting, "raise_cap": args.raise_cap,
           "strict": args.strict, "bundles": {}}
    if args.strict:
        cfg["bundles"] = {p: lab.bundle(p, preflop) for p in paths}

    cores = os.cpu_count() or 2
    jobs = args.jobs or (max(1, cores // 2) if args.strict else cores)
    tasks = [(r, p, cfg) for r in range(args.rounds) for p in paths]
    t0 = time.time()
    results = []
    with multiprocessing.Pool(jobs) as pool:
        for res in pool.imap_unordered(play_round, tasks):
            results.append(res)
            print("\r%d/%d tables" % (len(results), len(tasks)), end="", file=sys.stderr, flush=True)
    print("\r" + " " * 30 + "\r", end="", file=sys.stderr)

    by = {p: sorted((r for r in results if r["path"] == p), key=lambda r: r["round"]) for p in paths}

    def bb100(r, key="chips"):
        return r[key] / BIG_BLIND / max(r["hands"], 1) * 100

    base = [bb100(r) for r in by[control]]
    rows = []
    for p in paths:
        rs = by[p]
        xs = [bb100(r) for r in rs]
        m, ci = mean_ci(xs)
        dm, dci = mean_ci([x - b for x, b in zip(xs, base)])
        if p == control:
            verdict = "control"
        elif dci != dci:
            verdict = "unclear"
        elif dm - dci > 0:
            verdict = "better"
        elif dm + dci < 0:
            verdict = "worse"
        else:
            verdict = "unclear"
        decisions = sum(r["decisions"] for r in rs)
        rows.append({
            "name": names[p], "path": os.path.relpath(p, lab.KIT), "bb100": m, "ci": ci,
            "diff": dm, "diff_ci": dci, "verdict": verdict,
            "post_bb100": sum(bb100(r, "post_chips") for r in rs) / len(rs),
            "flop_pct": 100.0 * sum(r["flops"] for r in rs) / max(sum(r["hands"] for r in rs), 1),
            "ms_avg": sum(r["total_ms"] for r in rs) / max(decisions, 1),
            "ms_max": max(r["max_ms"] for r in rs),
            "bank_s": max(r["total_ms"] for r in rs) / 1000.0,
            "errors": sum(r["errors"] for r in rs),
            "timeouts": sum(r["timeouts"] for r in rs),
            "bank_out": sum(r["bank_out"] for r in rs),
            "first_error": next((r["first_error"] for r in rs if r["first_error"]), None),
            "rounds": xs,
        })
    rows[1:] = sorted(rows[1:], key=lambda r: -r["diff"])

    print("%d rounds x %d hands, %d seats, %s%s, seed %d, %s mode, preflop %s" % (
        args.rounds, args.hands, args.seats, args.betting,
        ", raise cap %d" % args.raise_cap if args.raise_cap else "", args.seed,
        "strict" if args.strict else "fast", os.path.relpath(preflop, lab.KIT)))
    print("opponents: %s\n" % ", ".join(sorted({lab.label(o) for o in opponents})))
    head = "%-22s %8s %7s %11s %7s %-8s %11s %6s %7s %7s %7s %6s" % (
        "strategy", "bb/100", "+/-", "vs control", "+/-", "verdict", "post bb/100", "flop%",
        "ms avg", "ms max", "bank s", "errors")
    if args.strict:
        head += " %8s %8s" % ("timeouts", "bank out")
    print(head)
    for r in rows:
        line = "%-22s %+8.1f %7.1f %+11.1f %7.1f %-8s %+11.1f %6.1f %7.3f %7.2f %7.2f %6d" % (
            r["name"][:22], r["bb100"], r["ci"], r["diff"], r["diff_ci"], r["verdict"],
            r["post_bb100"], r["flop_pct"], r["ms_avg"], r["ms_max"], r["bank_s"], r["errors"])
        if args.strict:
            line += " %8d %8d" % (r["timeouts"], r["bank_out"])
        print(line)
    for r in rows:
        if r["first_error"]:
            print("\n--- first error from %s ---\n%s" % (r["name"], r["first_error"]))
    print("\n%.1fs elapsed. 'bank s' is the worst round's total thinking time; the limit is 10 s."
          % (time.time() - t0))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"args": vars(args), "rows": rows}, f, indent=1)


if __name__ == "__main__":
    main()
