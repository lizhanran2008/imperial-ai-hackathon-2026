"""Compare two standalone bots with paired rounds on the official engine."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import random
from statistics import mean, stdev
import sys

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
from engine import FixedHandsTable  # noqa: E402
from engine.players import LocalPlayer, SubprocessPlayer  # noqa: E402

BIG_BLIND = 20
BYTE_LIMIT = 200_000
HOUSE = tuple(
    str(KIT / "examples" / name)
    for name in ("tight_aggressive.py", "calling_station.py")
)
# Two-sided 95% Student t critical values for 1 through 30 degrees of freedom.
T95 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)


class TrackedPlayer(SubprocessPlayer):
    """Count action corrections that the engine would otherwise apply silently."""

    def __init__(self, path):
        super().__init__(path, timeout_ms=10, bank_ms=10_000)
        self.invalid = 0

    def act(self, state):
        reply = super().act(state)
        if reply is None:
            return None
        action = reply.get("action")
        legal = state["legal_actions"]
        # The starter kit documents all_in as a raise, or a call if only
        # calling is possible. It is never included in legal_actions itself.
        if action == "all_in":
            valid = "raise" in legal or "call" in legal
        elif action == "raise":
            amount = reply.get("amount")
            valid = (
                "raise" in legal and type(amount) is int
                and state["min_raise_to"] <= amount <= state["max_raise_to"]
            )
        else:
            valid = action in legal
        if not valid:
            self.invalid += 1
        return reply


@dataclass
class Round:
    bb100: float
    hand_count: int
    decisions: int
    errors: int
    invalid_actions: int
    timeouts: int
    bank_out: int
    dead: bool
    max_decision_ms: float
    total_decision_ms: float
    error_samples: list
    opponent_timeouts: int
    opponent_bank_out: int


def house_player(path):
    spec = importlib.util.spec_from_file_location("house_bot", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return LocalPlayer(module.Agent)


def play(bot, opponents, seat, deal_seed, hands, betting, raise_cap):
    lineup = list(opponents)
    lineup.insert(seat, bot)
    with ExitStack() as resources:
        players = []
        for index, path in enumerate(lineup):
            if index == seat:
                player = TrackedPlayer(path)
            elif path in HOUSE:
                player = house_player(path)
            else:
                player = SubprocessPlayer(path, timeout_ms=10, bank_ms=10_000)
            resources.callback(player.close)
            players.append(player)
        result = FixedHandsTable(
            players, hands=hands, seed=deal_seed,
            config={"betting": betting, "raise_cap": raise_cap},
        ).play()

        other_players = [player for index, player in enumerate(players) if index != seat]
        for player in other_players:
            if getattr(player, "dead", False) or player.stats.errors:
                message = next(iter(player.stats.error_samples), "opponent process stopped")
                raise ValueError(f"Opponent failed: {message}")
        target = players[seat]
        stats = target.stats
        return Round(
            result["chips"][seat] / BIG_BLIND / result["hands"] * 100,
            result["hands"], stats.decisions, stats.errors, target.invalid,
            stats.timeouts, stats.bank_out, target.dead, stats.max_ms,
            stats.total_ms, stats.error_samples,
            sum(player.stats.timeouts for player in other_players),
            sum(player.stats.bank_out for player in other_players),
        )


def run_pair(job):
    index, master_seed, baseline, candidate, paths, seats, hands, betting, cap = job
    rng = random.Random(master_seed + index)
    opponents = [paths[i % len(paths)] for i in range(seats - 1)]
    rng.shuffle(opponents)
    seat = index % seats
    deal_seed = rng.getrandbits(64)
    args = (opponents, seat, deal_seed, hands, betting, cap)
    # Alternate execution order so one version doesn't always run first.
    if index % 2:
        new = play(candidate, *args)
        old = play(baseline, *args)
    else:
        old = play(baseline, *args)
        new = play(candidate, *args)
    return {
        "pair": index + 1, "seat": seat, "deal_seed": deal_seed,
        "opponents": opponents, "baseline": asdict(old), "candidate": asdict(new),
    }


def interval(values):
    """Student t interval over independent rounds (or paired differences)."""
    df = len(values) - 1
    if df <= len(T95):
        critical = T95[df - 1]
    else:
        # Cornish-Fisher expansion for the t quantile at larger sample sizes.
        z = 1.959963984540054
        critical = z + (z**3 + z) / (4 * df) + (5*z**5 + 16*z**3 + 3*z) / (96 * df**2)
    avg = mean(values)
    half_width = critical * stdev(values, xbar=avg) / len(values)**0.5
    return {"mean": avg, "low": avg - half_width, "high": avg + half_width}


def summarize(rounds):
    stats = {k: sum(row[k] for row in rounds) for k in (
        "errors", "invalid_actions", "timeouts", "bank_out", "decisions",
        "opponent_timeouts", "opponent_bank_out",
    )}
    stats["dead_rounds"] = sum(row["dead"] for row in rounds)
    stats["max_decision_ms"] = max(row["max_decision_ms"] for row in rounds)
    stats["max_round_seconds"] = max(row["total_decision_ms"] for row in rounds) / 1000
    stats["mean_decision_ms"] = (
        sum(row["total_decision_ms"] for row in rounds) / max(1, stats["decisions"])
    )
    return {**interval([row["bb100"] for row in rounds]), **stats}


def signature(path):
    return {"path": path, "sha256": sha256(Path(path).read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", help="Exact packaged bot.py to compare against")
    parser.add_argument("candidate", help="Packaged bot.py built from the PR")
    parser.add_argument("--rounds", type=int, default=24, help="Paired rounds (default: 24)")
    parser.add_argument("--hands", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=min(2, os.cpu_count() or 1))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seats", type=int, choices=(7, 8), default=8)
    parser.add_argument("--betting", choices=("no_limit", "pot_limit", "fixed_limit"), default="no_limit")
    parser.add_argument("--raise-cap", type=int, default=0)
    parser.add_argument("--opponent", action="append", metavar="BOT.py",
                        help="Repeat to set opponent mix, cycled to fill seats")
    parser.add_argument("--json", type=Path, metavar="PATH", help="Save per-round evidence")
    args = parser.parse_args()
    if args.rounds < 2 or args.hands < 1 or args.workers < 1 or args.raise_cap < 0:
        parser.error("Requires at least two rounds, positive hands/workers, and a nonnegative raise cap.")

    baseline, candidate = (str(Path(p).resolve()) for p in (args.baseline, args.candidate))
    opponents = [str(Path(p).resolve()) for p in (args.opponent or HOUSE)]
    if len(opponents) >= args.seats:
        parser.error("Pass at most seats minus one opponent files.")
    for name in [baseline, candidate, *opponents]:
        if not Path(name).is_file() or not name.endswith(".py"):
            parser.error(f"Expected a Python bot file: {name}")
    for name in (baseline, candidate):
        if Path(name).stat().st_size > BYTE_LIMIT:
            parser.error(f"Bot exceeds the {BYTE_LIMIT:,}-byte limit: {name}")

    workers = min(args.workers, args.rounds)
    jobs = [
        (i, args.seed, baseline, candidate, opponents, args.seats, args.hands,
         args.betting, args.raise_cap)
        for i in range(args.rounds)
    ]
    artifacts = {
        "baseline": signature(baseline), "candidate": signature(candidate),
        "opponents": [signature(path) for path in opponents],
    }
    try:
        if workers == 1:
            pairs = list(map(run_pair, jobs))
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                pairs = list(pool.map(run_pair, jobs))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Evaluation failed: {exc}\n")
    if any(signature(item["path"]) != item for item in [
        artifacts["baseline"], artifacts["candidate"], *artifacts["opponents"],
    ]):
        parser.exit(2, "Evaluation failed: a Bot file changed during the run.\n")

    versions = {name: summarize([pair[name] for pair in pairs]) for name in ("baseline", "candidate")}
    delta = interval([p["candidate"]["bb100"] - p["baseline"]["bb100"] for p in pairs])
    failure_keys = ("errors", "invalid_actions", "timeouts", "bank_out", "dead_rounds")
    if any(versions["candidate"][k] for k in failure_keys):
        verdict = "FAIL_STABILITY"
    elif any(versions["baseline"][k] for k in failure_keys):
        verdict = "BASELINE_UNSTABLE"
    elif any(s["opponent_timeouts"] or s["opponent_bank_out"] for s in versions.values()):
        verdict = "OPPONENT_UNSTABLE"
    elif args.rounds < 20 or args.hands != 1000:
        verdict = "SMOKE_ONLY"
    elif delta["low"] > 0:
        verdict = "PASS"
    else:
        verdict = "NO_SIGNIFICANT_IMPROVEMENT"

    report = {
        "settings": {"rounds": args.rounds, "hands": args.hands, "workers": workers,
                     "seed": args.seed, "seats": args.seats, "betting": args.betting,
                     "raise_cap": args.raise_cap},
        "artifacts": artifacts, "versions": versions, "delta_bb100": delta,
        "verdict": verdict, "pairs": pairs,
    }
    print(f"{args.rounds} paired rounds × {args.hands} hands, seed {args.seed}, {workers} worker(s)")
    for name, s in versions.items():
        print(f"{name.title()}: {s['mean']:+.2f} bb/100 (95% CI [{s['low']:+.2f}, {s['high']:+.2f}])")
        print(f"  errors={s['errors']} invalid={s['invalid_actions']} timeouts={s['timeouts']} "
              f"bank_out={s['bank_out']} dead_rounds={s['dead_rounds']}")
        print(f"  opponent timeouts={s['opponent_timeouts']} bank_out={s['opponent_bank_out']}")
        print(f"  avg/max decision {s['mean_decision_ms']:.3f}/{s['max_decision_ms']:.3f} ms; "
              f"max round {s['max_round_seconds']:.3f} s")
    print(f"Delta: {delta['mean']:+.2f} bb/100 (95% CI [{delta['low']:+.2f}, {delta['high']:+.2f}])")
    print(f"Verdict: {verdict}")
    if args.json:
        with args.json.open("x", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
