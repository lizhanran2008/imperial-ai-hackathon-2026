"""Check src/handeval.py against the tournament engine's evaluator.

    python tools/postflop/check_handeval.py            # 200,000 random hands
    python tools/postflop/check_handeval.py --hands 1000000

Exits non-zero on the first disagreement.
"""
import argparse
import random
import sys
import time

import lab  # noqa: F401  (puts the kit and src/ on the path)
import handeval
from engine.cards import evaluate, to_str

CASES = [
    # hole, board, expected subset of describe()
    (["As", "Kd"], ["Ah", "7c", "2d"], {"category": 1, "made": "top_pair"}),
    (["Qs", "Qd"], ["Jh", "7c", "2d"], {"category": 1, "made": "overpair", "overcards": 2}),
    (["9s", "9d"], ["Jh", "7c", "2d"], {"made": "underpair"}),
    (["7s", "6d"], ["Jh", "7c", "2d"], {"made": "middle_pair"}),
    (["2s", "6d"], ["Jh", "7c", "2d"], {"made": "bottom_pair"}),
    (["As", "Kd"], ["7h", "7c", "2d"], {"made": "board_pair", "overcards": 2}),
    (["Js", "7d"], ["Jh", "7c", "2d"], {"category": 2, "made": "two_pair"}),
    (["Js", "3d"], ["Jh", "7c", "7d"], {"made": "pair_and_board_pair"}),
    (["As", "3d"], ["Jh", "Jc", "7d", "7s"], {"made": "board_two_pair"}),
    (["7s", "7d"], ["Jh", "7c", "2d"], {"category": 3, "made": "set"}),
    (["7s", "Ad"], ["Jh", "7c", "7d"], {"made": "trips"}),
    (["As", "Kd"], ["7h", "7c", "7d"], {"made": "board_trips"}),
    (["As", "Ks"], ["7s", "2s", "Jd"], {"category": 0, "flush_draw": True, "overcards": 2}),
    (["As", "Kd"], ["7s", "2s", "Js", "4d"], {"flush_draw": True}),
    (["As", "Kd"], ["7s", "2s", "Js", "4s"], {"category": 5, "made": "flush", "flush_draw": False}),
    (["Ad", "Kd"], ["7s", "2s", "Js", "4s"], {"flush_draw": False}),  # the board's draw, not ours
    (["9s", "8d"], ["7h", "6c", "2d"], {"straight_draw": "open_ended"}),
    (["9s", "8d"], ["7h", "5c", "2d"], {"straight_draw": "gutshot"}),
    (["Ts", "8d"], ["Qh", "9c", "6d"], {"straight_draw": "open_ended"}),  # double gutshot
    (["As", "Kd"], ["7h", "6c", "5d", "4s"], {"straight_draw": "none"}),  # the board's draw, not ours
    (["Ts", "2d"], ["8h", "7c", "6d", "5s"], {"straight_draw": "gutshot"}),  # a 9 is ours alone at the top
    (["9s", "8d"], ["7h", "6c", "5d"], {"category": 4, "made": "straight", "straight_draw": "none"}),
    (["As", "Kd"], ["9h", "8c", "7d", "6s", "5h"], {"category": 4, "made": "board"}),
    (["Ts", "Kd"], ["9h", "8c", "7d", "6s", "5h"], {"category": 4, "made": "straight"}),
    (["As", "Ad"], [], {"category": 1, "made": "pocket_pair"}),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=200000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    deck = list(range(52))
    hands = []
    for _ in range(args.hands):
        ints = rng.sample(deck, rng.choice((5, 6, 7, 7, 7)))
        hands.append((ints, [to_str(c) for c in ints]))

    t0 = time.perf_counter()
    theirs = [evaluate(i) for i, _ in hands]
    t1 = time.perf_counter()
    ours = [handeval.rank(s) for _, s in hands]
    t2 = time.perf_counter()

    for (_, strs), a, b in zip(hands, theirs, ours):
        if a != b:
            sys.exit("MISMATCH on %s: engine %r, handeval %r" % (" ".join(strs), a, b))
    seen = sorted({a[0] for a in theirs})
    print("rank: %d hands identical to the engine (categories seen: %s)" % (len(hands), seen))
    print("      engine %.2f us/hand, handeval %.2f us/hand (handeval also parses the strings)"
          % ((t1 - t0) / len(hands) * 1e6, (t2 - t1) / len(hands) * 1e6))

    for hole, board, want in CASES:
        got = handeval.describe(hole, board)
        bad = {k: (v, got.get(k)) for k, v in want.items() if got.get(k) != v}
        if bad:
            sys.exit("describe(%s, %s) wrong: wanted/got %r" % (hole, board, bad))
    print("describe: %d fixed cases pass" % len(CASES))

    boards = []
    for _ in range(20000):
        ints = rng.sample(deck, rng.choice((5, 6, 7)))
        strs = [to_str(c) for c in ints]
        boards.append((strs[:2], strs[2:]))
    t0 = time.perf_counter()
    described = [handeval.describe(hole, board) for hole, board in boards]
    spent = time.perf_counter() - t0
    for (hole, board), d in zip(boards, described):
        if d["category"] != handeval.rank(hole + board)[0]:
            sys.exit("describe(%s, %s) category disagrees with rank()" % (hole, board))
    print("describe: %.2f us/call over %d random flops, turns and rivers"
          % (spent / len(boards) * 1e6, len(boards)))


if __name__ == "__main__":
    main()
