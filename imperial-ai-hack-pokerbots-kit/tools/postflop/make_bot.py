"""Turn a postflop strategy into one standalone bot file.

    python tools/postflop/make_bot.py                       # the champion, src/postflop.py
    python tools/postflop/make_bot.py tools/postflop/strategies/starter.py
    python tools/postflop/make_bot.py --preflop src/preflop.py --out bot_candidate.py

The result runs in local_sim.py and obeys the platform's single-file rule. It
is a lab tool: the team's uploaded bot.py comes from the integration lead's
build, not from here.
"""
import argparse
import os

import lab


def main():
    ap = argparse.ArgumentParser(description="Bundle a postflop strategy into one bot file.")
    ap.add_argument("strategy", nargs="?", default=lab.CHAMPION)
    ap.add_argument("--preflop", default=lab.BASELINE_PREFLOP)
    ap.add_argument("--out", default=None, help="output file (default: tools/postflop/out/<name>.py)")
    args = ap.parse_args()
    out = lab.bundle(lab.resolve(args.strategy), lab.resolve(args.preflop), args.out)
    print("%s (%d bytes of the %d allowed)" % (os.path.relpath(out), os.path.getsize(out), lab.SIZE_LIMIT))


if __name__ == "__main__":
    main()
