# Poker Bot evaluation

## Before marking a strategy PR ready

From the repository root on your task branch, commit your in-scope source
changes and make sure the working tree is clean. Sync and build:

```sh
git fetch origin
git merge origin/main
kit=imperial-ai-hack-pokerbots-kit
run_dir=$(mktemp -d)
git rev-parse HEAD origin/main
python3 "$kit/build.py"
cp "$kit/bot.py" "$run_dir/candidate.py"
```

Stop if sync or build fails. If GitHub is unavailable in your agent, ask your
teammate to sync the branch from their shell before building. For the baseline,
use the exact uploaded `bot.py` from the integration lead. If nothing has been
uploaded, take the generated artifact from the same verified main commit:

```sh
git show "origin/main:$kit/bot.py" > "$run_dir/baseline.py"
```

Confirm that the baseline file is available before testing. For a quick check,
then the full comparison:

```sh
python3 "$kit/harness/eval.py" "$run_dir/baseline.py" "$run_dir/candidate.py" \
  --rounds 2 --hands 50 --workers 1

python3 "$kit/harness/eval.py" "$run_dir/baseline.py" "$run_dir/candidate.py" \
  --rounds 24 --hands 1000 --workers 2 --seed 42 --json "$run_dir/report.json"
```

A clean short run prints `SMOKE_ONLY` and exits 1. For the full run,
`PASS` means both versions were stable and the lower bound of the paired
95% confidence interval was above zero. If a change only supplies data that
strategies do not use yet, explain the expected neutral score and show
correctness checks for the data. If the run shows timeouts, rerun with
`--workers 1` and report both outcomes. Use a fresh JSON path on reruns.

In the PR, paste the tested head and main SHAs, baseline identity, exact
command, score difference and interval, errors, invalid actions, timeouts,
and bank-outs. Include checks specific to your module. The generated
`bot.py` is shared: keep your source changes on the branch and leave the
official generated file to the integration lead. If it was clean before
your local build, restore it after saving the candidate copy:

```sh
git restore -- "$kit/bot.py"
```

## Comparing two existing artifacts

From the repository root:

```sh
python3 imperial-ai-hack-pokerbots-kit/harness/eval.py \
  /tmp/live-bot.py /tmp/candidate-bot.py \
  --rounds 24 --hands 1000 --workers 2 --seed 42 --json /tmp/poker-eval.json
```

The simulator runs each version in its own copy of the same table, using
the same deal seed, focal seat, and opponent lineup for each pair. By default
it uses the two deterministic house strategies via the engine's in-process
adapter, so a slow host cannot change their actions through a timeout.
Both versions under test and any custom opponents use the official
timed subprocess adapter. Repeat `--opponent FILE`
to set a lineup, `--seats 7` for smaller tables, or use `--betting` and
`--raise-cap` to match the format in play. Use self-contained, reviewed bots.
The official local runner is a subprocess runner, not the hosted sandbox.
Custom bots that seed themselves from system entropy can vary across runs.

The report includes both artifacts' SHA-256, each paired round, bb/100, the
paired difference and its 95% t interval, decision times, and failures. Each
independent paired round is one observation. A strong result against the
default house bots may disappear against other lineups. Keep some deals and
opponents aside for the final check after tuning.

Exit 0 means `PASS`: at least 20 full rounds per version, zero recorded
failures in either version, and a paired interval whose lower bound is above
zero. Exit 1 reports a failed gate, an inconclusive improvement or a short
smoke run. For a quick plumbing test, use `--rounds 2 --hands 50`.
The engine's action and round time limits stay at 10 ms and 10 s. If the
parallel run shows timeouts, rerun with `--workers 1` to check whether the
result persists under lighter CPU load and report both runs. A clean local
run does not certify the hosted sandbox or catch exceptions swallowed inside
a bot. The maximum is wall-clock time, including IPC and host scheduling.
It can exceed 10 ms even when the local runner records no timeout. Report
that difference and use a quiet serial run before judging release timing.
Alongside the score, attach the PR head, tested main, and any strategy
specific checks when asking the integration lead to review.
