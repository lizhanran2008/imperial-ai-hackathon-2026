"""Paired comparison of two packaged bots at any table size.

    python3 tools/postflop/paired_eval.py BASELINE.py CANDIDATE.py --seats 2 --opponent X.py

harness/eval.py only offers 7 or 8 seats. This reuses its pairing, timing and
statistics unchanged (same deals, seat and opponents for both versions, the
real 10 ms and 10 s limits) and adds 2 to 6 seats, for heads-up and three-way
tables. With --versus the baseline bot itself fills the other seats, so the
candidate plays against the baseline and the baseline against itself.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
KIT = HERE.parent.parent
sys.path.insert(0, str(KIT / "harness"))
sys.path.insert(0, str(KIT))

import eval as harness  # noqa: E402  (the team's harness/eval.py)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--rounds", type=int, default=24)
    ap.add_argument("--hands", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=min(2, os.cpu_count() or 1))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--seats", type=int, choices=range(2, 9), default=8)
    ap.add_argument("--betting", choices=("no_limit", "pot_limit", "fixed_limit"), default="no_limit")
    ap.add_argument("--raise-cap", type=int, default=0)
    ap.add_argument("--opponent", action="append", metavar="BOT.py")
    ap.add_argument("--versus", action="store_true", help="fill the other seats with the baseline bot")
    ap.add_argument("--label", default="")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    baseline, candidate = (str(Path(p).resolve()) for p in (args.baseline, args.candidate))
    if args.versus:
        opponents = [baseline]
    else:
        opponents = [str(Path(p).resolve()) for p in (args.opponent or harness.HOUSE)]
    jobs = [(i, args.seed, baseline, candidate, opponents, args.seats, args.hands, args.betting, args.raise_cap)
            for i in range(args.rounds)]
    try:
        if args.workers == 1:
            pairs = list(map(harness.run_pair, jobs))
        else:
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                pairs = list(pool.map(harness.run_pair, jobs))
    except (ValueError, OSError) as exc:
        sys.exit("Evaluation failed: %s" % exc)

    versions = {name: harness.summarize([pair[name] for pair in pairs]) for name in ("baseline", "candidate")}
    delta = harness.interval([p["candidate"]["bb100"] - p["baseline"]["bb100"] for p in pairs])
    names = ", ".join(sorted({Path(o).stem for o in opponents}))
    print("%s%d seats, %s, %d rounds x %d hands, opponents: %s" % (
        args.label and args.label + ": ", args.seats, args.betting, args.rounds, args.hands,
        "the baseline bot" if args.versus else names))
    for name in ("baseline", "candidate"):
        v = versions[name]
        print("  %-9s %+9.2f bb/100 (95%% CI %+.2f to %+.2f)  errors=%d invalid=%d timeouts=%d bank_out=%d  "
              "avg/max %.3f/%.1f ms  opp timeouts=%d" % (
                  name, v["mean"], v["low"], v["high"], v["errors"], v["invalid_actions"], v["timeouts"],
                  v["bank_out"], v["mean_decision_ms"], v["max_decision_ms"], v["opponent_timeouts"]))
    sig = "candidate better" if delta["low"] > 0 else "candidate worse" if delta["high"] < 0 else "no clear difference"
    print("  delta     %+9.2f bb/100 (95%% CI %+.2f to %+.2f)  %s" % (delta["mean"], delta["low"], delta["high"], sig))
    if args.json:
        args.json.write_text(json.dumps({"settings": vars(args) | {"json": str(args.json)}, "versions": versions,
                                         "delta_bb100": delta, "pairs": pairs}, indent=1, default=str))


if __name__ == "__main__":
    main()
