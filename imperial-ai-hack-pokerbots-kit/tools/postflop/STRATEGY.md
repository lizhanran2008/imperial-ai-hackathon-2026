# Postflop target strategy

Owner: Macro1027. Status: design target for the lab, written 14 November 2026.
Nothing here changes the team contract in `PROJECT.md`; where the design needs
something the contract does not give, the section "Contract gaps" says so and
gives the fallback to use until the owners agree a change.

`README.md` in this folder explains how to run the lab. This file says what to
build in it.

## Problem

Given a hand that has reached the flop, choose check, fold, call or raise-to on
each street to win the most chips at a 7- or 8-seat table with 100 big blind
stacks. The usual approach, equity against random hands plus pot odds,
overrates our hand once an opponent bets, because a bet means their hand is no
longer random.

## Success criteria

| Criterion | Target | How it is measured |
| --- | --- | --- |
| Strength | `better` than the baseline candidate (equity against random hands plus pot odds) with the same preflop on both sides | `arena.py --control strategies/baseline_equity.py`, 200 or more rounds |
| No losing segment | Not `worse` than the baseline against any zoo line-up: station, nit, maniac, default AI-written bot | one arena run per line-up with `--opponents` |
| Speed | Worst postflop decision under 3 ms, average under 1.5 ms, fallback path under 0.2 ms | `arena.py --strict` |
| Safety | Every output is a legal action; any exception returns the fallback action | unit checks plus zero errors in the arena |

The 1.5 ms average is the `PROJECT.md` budget for `postflop.decide`. The 3 ms
worst case sits inside its 5 ms worst case for the whole `act` call.

Two things in this table do not exist yet and are the first lab tasks:
`strategies/baseline_equity.py`, and the zoo. Only `examples/calling_station.py`
matches an archetype today. Until David's gauntlet bots arrive, stand-ins go in
`tools/postflop/zoo/` and are passed with `--opponents`.

## Scope

- **In:** opponent range model, equity estimate, hand and board features,
  action and size selection, exploit hooks that read `profiles`, fallback table.
- **Out:** preflop, the opponent model's own statistics, solver output, bluffs
  into two or more opponents, memory across rounds (the platform creates a new
  `Agent` each round, so there is none to use).
- **Stretch:** bet-size tells learned from hands shown at showdown.

## What the bot sees (answers from the kit)

Sources: the kit `README.md`, `engine/game.py` and `engine/players.py`.

1. **Information available.**
   - Every `state` carries `history`: every action by every seat in the current
     hand so far, with street and amount. Blinds are included.
   - Opponents are identified by seat number only. Seats are fixed for the
     1,000 hands of a round, so a seat is a stable identity within a round.
     Everyone is reseated each round and a new `Agent` is created, so nothing
     identifies an opponent across rounds.
   - `on_hand_end(summary)` is sent to every seat after every hand, including
     hands we folded. It holds the full `history`, the `board`, `winners` and
     `shown`.
   - `shown` holds the hole cards of every seat still in at showdown, winners
     and losers alike. It is empty when the hand ended by everyone else folding.
2. **Owners.** Preflop is cntrlaltdlt (`src/preflop.py`). The tracker is David
   (`src/opponents.py`). Integration and the `Agent` wrapper are Zhanran
   (Issue #7, still open, so no stubs are on main yet). What they deliver
   against this design's wishes is in "Contract gaps".
3. **The 10 s bank is total thinking time, not overflow.** The engine subtracts
   the wall time of every decision, transport included, from 10 s. Each
   decision is also limited to 10 ms, or to what is left in the bank if less.
   At zero, every remaining decision in the round is auto-played as check,
   otherwise fold. `on_hand_end` is not timed, but it runs in the same process,
   so slow work there delays the next decision.
4. **Scoring.**
   - Stacks reset to 2,000 every hand, so each hand is an independent chip
     decision: no survival or stack-preservation value. Maximise expected chips.
   - Saturday standings are bb/100 over every counted hand (rounds from 3:00 to
     7:25 p.m.; the 12:35 to 1:55 p.m. practice rounds do not count).
   - Sunday bucket tables are seeded from Saturday; the top two by chips at
     each table reach the final. The final is 5,000 hands at one table and the
     most chips wins.

Other kit rules that bind this module: `betting` may be `no_limit`, `pot_limit`
or `fixed_limit` and `raise_cap` may be set, so every size is clamped to
`min_raise_to` and `max_raise_to` and the strategy must still make sense when
only one size is legal. Issue #7 states a 200 KB limit on the uploaded file,
which bounds any precomputed table.

## Contract gaps

The design assumed inputs that the current contract does not provide. The
fallbacks keep the module inside the contract; the requests are additive
changes that need an Issue and the owners' agreement under `docs/INTERFACES.md`
before anyone relies on them.

| Design wants | Contract provides | Fallback inside this module | Request |
| --- | --- | --- | --- |
| Last preflop aggressor; each opponent's preflop action class (open, call, 3-bet, limp, blind defend) | Nothing from `preflop`; `state["history"]` has the preflop actions | Derive both from `history` once per hand and cache by `hand_number` | None needed |
| Fold-to-bet by size bucket | One `fold_to_bet` per seat | Scale the single rate by bet size with a curve in the parameter block | David: `fold_to_bet` split into small, medium and large bets |
| Aggression by street | One `aggression` per seat | Use the single value on every street | David: per-street values |
| Showdown bluff rate | `showdown` is the share of flops that reach showdown, which is a different thing | A prior bluff rate in the parameter block, moved up or down by `aggression` and `style` | David: share of shown bets and raises that were weak hands |
| Dead-bot flag | Not provided | Treat a seat as dead when `hands` is at least 40, `pfr` and `aggression` are about 0 and `fold_to_bet` is at least 0.95 | David: a `dead` flag |
| Style label | `unknown`, `tight_passive`, `tight_aggressive`, `loose_passive`, `loose_aggressive`, `maniac` | Station is `loose_passive`; nit is `tight_passive`; maniac is `maniac`; over-folder is read from `fold_to_bet`, not from the label | None needed |

`PROJECT.md` also says, under Role 3 and under non-goals, that equity comes
from precomputed tables and that there is no simulation at decision time that
risks the time bank. Sampled equity as described below is a bounded version of
what that text rules out. Until the lead and the team accept a change to that
wording, sampled equity is a lab candidate that must pass `--strict`, with the
table-based estimate as the alternative candidate.

## Decision pipeline

1. **Ranges.** Each opponent still in the hand gets a weight per two-card
   combination, seeded from their preflop action class. When the opponent bets
   or raises, weight moves up for strong made hands and strong draws on the
   current board and down for air, by one minus that opponent's bluff rate.
   Checks and calls move weight mildly toward medium hands.
2. **Equity.** Heads-up on the river: exact against the weighted range. Flop,
   turn and multiway: sampled trials from the weighted ranges. Compute once per
   street and again only after a range update.
3. **Features.** Made-hand class, draw class (flush draw, open-ended, gutshot,
   combination), board texture (paired, one suit, connected), stack-to-pot
   ratio, opponents left, in or out of position, whether we were the last
   aggressor.
4. **Not facing a bet.**
   - Value bet when equity against the hands that call is above 50% heads-up,
     60% against two opponents, 70% against three or more.
   - Pick the size from 33%, 66% and 100% of the pot and all-in by highest
     estimated chip gain, using each opponent's fold rate for that size.
   - Heads-up as the last aggressor on a dry board, bet at a set frequency.
     Bet strong draws heads-up.
   - Check medium-strength hands. Never bluff into two or more opponents.
5. **Facing a bet.**
   - Call when equity against the betting range beats the pot odds plus a
     margin: 3 points heads-up and 8 multiway to start, larger with streets
     left to play and when out of position.
   - Raise for value above about 70% equity against the range that continues.
     Raise combination draws heads-up at a low frequency.
   - Against a turn or river raise, fold one-pair hands by default. The working
     assumption is that this field rarely bluffs with a raise; David's first
     analysis note should confirm or overturn it.
6. **Stack-off rule.** Put the whole stack in only when equity against the
   opponent's stack-off range is above 55%. Take that range as two pair or
   better unless the profile says otherwise.
7. **Exploit hooks.** Each has its own on/off switch and a cap on how far it
   can move a threshold.
   - Station: no bluffs, thinner value bets, larger sizes.
   - Over-folder: more continuation bets and river bluffs, smaller value sizes.
   - Maniac: check and call wider, slow-play strong hands, never fold top pair
     to one bet.
   - Passive seat betting big: treat as strong and fold more.
   - Dead bot: minimum bet at every opportunity.
8. **Fallback.** A small table of made-hand class by size of bet faced, used on
   a missed deadline or any exception.

## Constraints

- **Time targets:** range update about 0.3 ms, equity up to 2 ms, selection
  0.1 ms.
- **Measured cost** (this lab's `handeval`, Python 3.12.2, Apple M3, 14
  November): `rank` on seven cards takes 2.9 µs and `describe` 5.2 µs. 300
  trials with uniformly random opponent hands on the flop take 2.5 ms against
  one opponent, 3.1 ms against two and 3.5 ms against three.
- **What that means for the pipeline as written:**
  - 300 to 600 trials do not fit in 2 ms. About 200 heads-up or 150 multiway
    do on this machine, before the extra cost of weighted sampling and with no
    allowance for a slower platform CPU. The trial count is a parameter, set
    from `--strict` results with at least a factor of two in hand.
  - Exact river equity over all 990 opponent combinations costs about 2.9 ms.
    Either drop combinations below a weight floor first or sample.
  - Reweighting every combination by its strength class on each bet costs
    about 5 ms with `describe`, not 0.3 ms. Prototype the cheaper form first:
    keep only the preflop weights as a table, and apply the postflop action
    weights to the hands drawn in each trial, so only sampled hands are
    classified.
  - The bank is not the tight limit: 600 postflop decisions at 3 ms is 1.8 s of
    the 10 s. The 10 ms per-decision limit with transport and scheduling jitter
    is.
- Mixed frequencies come from a seeded generator. No clock reads inside a
  decision except the deadline check.
- About 30 thresholds live in one parameter block at the top of the file so the
  tuner can reach them.

## Plan

1. **Hour 1:** fallback table and legal-action clamp, so there is always a
   postflop that can ship. Add `strategies/baseline_equity.py` as the control.
2. **Hours 2 to 4:** ranges, equity and steps 4 to 6. Gate against the baseline.
3. **Hours 4 to 6:** exploit hooks behind their switches. Remove each in turn
   and keep only those whose removal makes the result `worse`.
4. **After:** tune the parameter block against the zoo with an evolution
   strategy.

Counted rounds start at 3:00 p.m., so step 1 is what the team can rely on for
the first upload.

## Still open

- Whether the team accepts bounded sampling at decision time (see "Contract
  gaps").
- Whether David can add the four requested profile fields, and by when.
- The platform CPU speed relative to the machine measured above.
- No task Issue exists yet for the postflop work. `AGENTS.md` requires one
  before the work is handed off.
