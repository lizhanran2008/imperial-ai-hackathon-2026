# Postflop lab

A place to try many postflop strategies and find out which one wins more chips.
Owner: Macro1027. Run everything from `imperial-ai-hack-pokerbots-kit/`.

What to build is in [`STRATEGY.md`](STRATEGY.md): the target decision pipeline,
its success criteria, what the bot can see, and where the design needs more
than the team contract provides. Read it before starting a candidate.

```
src/handeval.py                      hand evaluator and hand description (shared with the team)
src/postflop.py                      the current champion: what the team's bot uses after the flop
tools/postflop/strategies/<name>.py  one candidate per file
tools/postflop/strategies/starter.py the control every candidate is measured against; also the frozen preflop
tools/postflop/arena.py              compare strategies on the same cards
tools/postflop/make_bot.py           bundle a strategy into one standalone bot file
tools/postflop/check_handeval.py     check the evaluator against the tournament engine
tools/postflop/agent_wrapper.py      stand-in for the team's Agent wrapper
```

## Try a strategy

```bash
cp tools/postflop/strategies/_template.py tools/postflop/strategies/my_idea.py
# edit decide(state, profiles)
python tools/postflop/arena.py tools/postflop/strategies/my_idea.py --rounds 200
```

A candidate is one self-contained file that defines `decide(state, profiles)`,
imports only the standard library and `handeval`, and returns an action dict.
The rules are at the top of `_template.py`.

Keep embedded tables small. The integration task (Issue #7) records a 200 KB
limit on the uploaded `bot.py`, which has to hold every module, not just this
one. `make_bot.py` prints the size of the bundle and warns above the limit.

Useful runs:

```bash
python tools/postflop/arena.py --rounds 200                 # champion and every candidate
python tools/postflop/arena.py --rounds 8 --strict          # real 10 ms / 10 s limits, bundled single file
python tools/postflop/arena.py --rounds 100 --betting pot_limit
python tools/postflop/arena.py --rounds 100 --betting fixed_limit
python tools/postflop/arena.py --rounds 100 --raise-cap 3 --seats 7
python tools/postflop/arena.py --control src/postflop.py tools/postflop/strategies/my_idea.py
python tools/postflop/arena.py --opponents examples/*.py tools/postflop/strategies/*.py
python tools/postflop/arena.py ../../other-worktree/imperial-ai-hack-pokerbots-kit/tools/postflop/strategies/x.py
python tools/postflop/check_handeval.py
python tools/postflop/make_bot.py tools/postflop/strategies/my_idea.py && python local_sim.py tools/postflop/out/my_idea.py
```

The last `--opponents` form seats other candidates at the table, which is the
closest thing to a real field until there are better gauntlet bots.

## Reading the result

`verdict` is `better` or `worse` only when the 95% interval of the round-by-round
difference against the control excludes zero. `unclear` means run more rounds.
200 rounds of two strategies takes about 25 seconds on 8 cores.

Three warnings:

- The three house bots are very weak (the starter bot wins about +1,200 bb/100
  against them). Beating them harder is not the same as beating real teams. A
  result counts for more when it also holds against other candidates and
  against gauntlet bots built from real rounds.
- Times in fast mode are a rough guide. `--strict` is the real check. Even the
  control picks up a stray timeout per 20,000 decisions or so from scheduling
  jitter, so compare a candidate's timeouts with the control's in the same run.
- Strategy exceptions are counted in fast mode only. In `--strict` the bundled
  bot catches them itself and plays check or fold, so run both modes.

## Promoting a winner

A candidate replaces `src/postflop.py` when all of these hold:

1. `better` than the current champion (`--control src/postflop.py`) at 200 or more rounds.
2. Not `worse` under `pot_limit`, `fixed_limit`, `--raise-cap 3` and `--seats 7`.
3. Zero errors, and in `--strict` no more timeouts than the control, worst
   decision under 3 ms, average under 1.5 ms and `bank s` well under 10.
4. Not `worse` with other candidates as opponents.
5. Not `worse` than `strategies/baseline_equity.py` against any zoo line-up
   (station, nit, maniac, default AI-written bot), one `--opponents` run each.
   The baseline and the zoo are the first tasks in `STRATEGY.md`; until they
   exist this check cannot be claimed as passed.

Copy the file over `src/postflop.py`, record the arena output on the task Issue,
and hand off by PR as `WORKFLOW.md` describes.

## How this fits the team's build

The lab runs on its own so that postflop work does not wait for anything else.
Three pieces here stand in for the integration lead's (Issue #7), follow the
contract in `PROJECT.md`, and should give way to the real ones once they are on
main:

| Here | Real one |
| --- | --- |
| `agent_wrapper.py`: the `Agent`, `safe_action`, default profiles | the Agent wrapper and `src/common.py` |
| `lab.bundle` / `make_bot.py` | `build.py` |
| `strategies/starter.py` as the preflop | `src/preflop.py` (pass `--preflop src/preflop.py`) |

Issue #7 also creates first versions of `src/handeval.py` and `src/postflop.py`
as stubs. This branch has real ones at the same paths, so the order in which
the two reach main has to be agreed with the integration lead.

## Working in several workspaces at once

Each workspace is its own branch and worktree and writes one new file under
`strategies/` (plus, if it needs generated tables, its own folder under
`tools/postflop/`). Nobody but the lab workspace edits `arena.py`, `lab.py`,
`agent_wrapper.py`, `src/handeval.py` or `src/postflop.py`, so branches cannot
conflict. The arena reads strategy files by path, so a candidate in another
worktree can be compared without merging anything.

| Workspace | Writes | Idea to test |
| --- | --- | --- |
| lab (this one) | arena, evaluator, champion, `strategies/fallback.py` | Keeps the tools working, runs the league, promotes winners. First job: the fallback table and legal-action clamp (`STRATEGY.md` step 8) |
| baseline | `strategies/baseline_equity.py`, `tools/postflop/zoo/` | The control from the success criteria: equity against random hands plus pot odds. Also the stand-in zoo bots until the gauntlet bots exist |
| ranges | `strategies/ranges.py` | The main line, `STRATEGY.md` steps 1 to 6: opponent ranges from preflop action class, reweighted on bets; equity against those ranges; value, call, raise and stack-off rules |
| equity | `strategies/equity.py` + `tools/postflop/equity_tables/` | The same decisions as `ranges` with equity from precomputed tables instead of sampling, in case sampling fails the time check or the team keeps the no-simulation rule |
| value | `strategies/value.py` | Bet made hands bigger and thinner, never bluff: the station hook tested alone |
| pressure | `strategies/pressure.py` | Bet the flop after raising preflop and keep betting on good cards: the over-folder hook tested alone |
| adaptive | `strategies/adaptive.py` | `ranges` plus the exploit hooks of step 7, each behind its own switch; needs the opponent model for real profiles |
| structures | `strategies/limit.py` | Separate rules for fixed-limit and pot-limit, where bet sizes and odds differ |
| tuner | `tools/postflop/tune/` | Search the parameter block of the champion with the arena against the zoo |
| attacker | bot files handed to the opponent-modelling owner | Write bots that beat the current champion, to expose its leaks |

Order: lab fallback and baseline first, then ranges and equity side by side.
Value and pressure need nothing but this lab and can run alongside. Adaptive
waits for `src/opponents.py`. Tuner and attacker start once a champion has
survived a league round.
