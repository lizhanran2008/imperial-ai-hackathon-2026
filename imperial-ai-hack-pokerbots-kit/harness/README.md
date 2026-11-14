# Poker Bot evaluation

Build and save the candidate from the PR's exact head in a separate checkout.
Use the actual uploaded file as the baseline. If nothing is live, build the
current main and report that it was the baseline.

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
