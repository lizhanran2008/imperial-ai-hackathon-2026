# Project alignment

Event: Imperial AI Hackathon, 14 November 2026.
Phase: building a bot for the AlgoSoc Pokerbots competition. The organisers' starter kit is in `imperial-ai-hack-pokerbots-kit/`; its `README.md` is the authoritative rule and API reference.

Status of this document: the role split and module contract below were proposed by Macro1027 and take effect when the integration lead merges the PR that introduces them. Until then they are a proposal, not a team decision.

## Team and roles

| Member | Role | Owned paths (inside `imperial-ai-hack-pokerbots-kit/`) |
| --- | --- | --- |
| lizhanran2008 (Zhanran) | Integration and evaluation | `build.py`, `harness/`, `src/common.py`, generated `bot.py` |
| cntrlaltdlt | Preflop strategy | `src/preflop.py`, `tools/preflop/` |
| Macro1027 (Marco) | Postflop strategy | `src/postflop.py`, `src/handeval.py`, `tools/postflop/` |
| Davidlikestoprogram (David) | Opponent modelling and data | `src/opponents.py`, `analysis/`, `examples/` (new gauntlet bots) |

Event integration lead: lizhanran2008, assisted by their delegated agent.
Backup: TBD before parallel implementation.

All four members may implement features. Repository ownership and integration duty are separate; duty can rotate by explicit handover. Each person chooses their own editor, AI and Git client. Nobody edits `engine/`: it is the organisers' tournament engine and must stay identical to what the platform runs.

## What the competition requires

These come from the kit README and shape every role.

- **Game:** No-Limit Texas Hold'em at tables of 7 or 8 bots. Every hand starts each bot on 2,000 chips (100 big blinds) with blinds fixed at 10/20. A round is 1,000 hands at one table against the same opponents.
- **Score:** big blinds won per 100 hands (bb/100) over every counted hand. Folding every hand scores about −19 bb/100.
- **Deliverable:** one uploaded file, `bot.py`, exposing a class named `Agent`, importing only the Python standard library. It runs on Python 3.12 with no internet, no other files, 512 MB of memory and one CPU core.
- **Time:** 10 ms per decision, including transport, and a 10 s thinking bank per round. A late decision is auto-played as check, otherwise fold. When the bank is empty every remaining decision in the round is auto-played.
- **Memory:** a fresh `Agent()` is created per table per round. Nothing carries over between rounds.
- **Errors:** an exception or an illegal `check` facing a bet becomes a fold. Raises outside the legal range are moved to the nearest legal amount.
- **Rule changes:** the organisers may switch to pot-limit or fixed-limit, or cap raises per street. Every `state` carries `betting` and `raise_cap`, and the bot must obey them.
- **Schedule (Saturday):** practice rounds every 5 minutes from 12:35 to 1:55 p.m., which do not count; counted rounds every 5 minutes from 3:00 to 7:25 p.m. A new upload plays from the next round. Sunday: bucket tables 9:00–11:55 a.m., top two per table reach a 5,000-hand final.

## How the bot is assembled

Because only one file is uploaded, four people cannot all edit `bot.py`. Each role writes its own module under `src/`, and `build.py` joins them into the single `bot.py` that gets uploaded. `bot.py` is generated output: nobody edits it by hand.

Decision flow inside the generated `Agent`:

1. `on_table_start(info)` creates one `OpponentModel` and calls its `start(info)`.
2. `act(state)` asks the model for `profiles()`, then calls `preflop.decide(state, profiles)` when `state["street"] == "preflop"`, otherwise `postflop.decide(state, profiles)`.
3. The returned action passes through `common.safe_action(state, action)`, which makes it legal for the current betting structure.
4. The whole of `act` is wrapped so that any exception returns check when legal, otherwise fold.
5. `on_hand_end(summary)` calls `OpponentModel.observe(summary)`.

### Shared data shapes

`state`, `info` and `summary` are exactly the dictionaries documented in the kit README. Modules read them and never modify them.

**Action** (returned by both `decide` functions), one of:

```python
{"action": "fold"}
{"action": "check"}
{"action": "call"}
{"action": "raise", "amount": 200}   # integer "raise to" total for this street
{"action": "all_in"}
```

**Profiles** (returned by `OpponentModel.profiles()`): a dict keyed by integer seat, one entry for every seat at the table including seats with no data yet. Each entry is a dict with these keys, always present:

| Key | Type | Meaning | Value when there is too little data |
| --- | --- | --- | --- |
| `hands` | int | Hands observed for this seat this round | 0 |
| `vpip` | float 0–1 | Share of hands where the seat voluntarily put chips in preflop | population default |
| `pfr` | float 0–1 | Share of hands where the seat raised preflop | population default |
| `three_bet` | float 0–1 | Share of chances where the seat re-raised a preflop raise | population default |
| `aggression` | float 0–1 | Postflop bets and raises as a share of bets, raises and calls | population default |
| `fold_to_bet` | float 0–1 | Share of postflop bets faced that the seat folded to | population default |
| `showdown` | float 0–1 | Share of flops seen that reached showdown | population default |
| `style` | str | One of `unknown`, `tight_passive`, `tight_aggressive`, `loose_passive`, `loose_aggressive`, `maniac` | `unknown` |

Strategy modules must play sensibly when every seat is `unknown`. The population defaults live in `src/common.py` so that all three modules agree on them.

### Time budget

The 10 s bank spread over a round leaves only a few milliseconds per decision on average, and the 10 ms limit includes transport. Proposed limits, measured by the harness on the lead's machine:

| Piece | Limit |
| --- | --- |
| Whole `act` call | 2 ms average, 5 ms worst case |
| `preflop.decide` | 0.2 ms average |
| `postflop.decide`, including hand evaluation | 1.5 ms average |
| `OpponentModel.profiles` | 0.1 ms average |
| `OpponentModel.observe` | 1 ms average |
| Importing the generated `bot.py` | under 1 s, under 100 MB |

`on_hand_end` is not timed by the engine, but it runs in the same process as `act`, so slow work there delays the next decision and eats its time.

## Role 1 — Integration and evaluation (Zhanran, lizhanran2008)

**Purpose.** Make it possible for three people to build strategy in parallel, decide with evidence which version is best, and be the only person who uploads.

**Expected work.**

- `build.py`: joins `src/common.py`, `src/handeval.py`, `src/opponents.py`, `src/preflop.py` and `src/postflop.py` plus the `Agent` wrapper into one `bot.py`. It fails loudly if a module imports anything outside the standard library or if the result does not load.
- `src/common.py`: shared constants and helpers used by every module, so nobody writes their own copy.
- `harness/`: an evaluation runner on top of the kit's `local_sim.py` and `engine/`, without changing either.
- The `Agent` wrapper described in "How the bot is assembled", including the exception fallback.
- The upload gate and the record of what was uploaded when.
- Registering the contract below in `docs/INTERFACES.md` and replacing the UNCONFIGURED commands in the root `README.md` with the real ones.

**Inputs.**

- The three strategy modules, each exposing the functions defined in their sections.
- Candidate bot files to compare, the house bots in `examples/`, and David's gauntlet bots.
- Round results and hand histories from the competition site, via David.

**Outputs.**

- `bot.py`: the generated single file, with a comment at the top naming the commit it was built from.
- `common.safe_action(state, action) -> action`: returns a legal action for the current `betting` and `raise_cap`. It clamps `amount` to an integer between `min_raise_to` and `max_raise_to`, turns a raise into a call when raising is not allowed, turns a call into a check when `to_call` is 0, and never returns `check` when there is a bet to call.
- `common.position(state) -> int`: seats after the button, 0 for the button itself, counting only seats that are in the hand.
- `common.DEFAULT_PROFILE`: the population-default profile dict.
- A harness report per candidate: bb/100 with a confidence interval, timeouts, errors, bank-outs, average and worst decision time, split by opponent line-up, for no-limit, pot-limit, fixed-limit and a raise cap.
- A go or no-go decision for each upload, recorded on the PR.

**Done when.**

- `python build.py` produces a `bot.py` that `python local_sim.py --rounds 20 --seed 1` runs with zero timeouts, errors and bank-outs.
- The harness can compare two bots on the same seeded cards and report whether the difference is larger than the noise.
- A version is uploaded before the practice rounds end, and a gated version is frozen before 3:00 p.m.

## Role 2 — Preflop strategy (cntrlaltdlt)

**Purpose.** Decide every action taken before the flop. Most hands end here, so this module sets how many pots the bot enters and with what.

**Expected work.**

- A strength ordering of all 169 distinct starting hands (pairs, suited, offsuit).
- Ranges by position for a 7- or 8-seat table at 100 big blinds: which hands open-raise, which call a raise, which re-raise, which continue against a re-raise, and which go all in.
- Handling of every preflop situation: folded to us, limpers ahead, one raise ahead, raise and callers, re-raise ahead, all-in ahead, and play from the small and big blind.
- Raise sizing as a function of position, limpers and previous raises.
- Adjustments from opponent profiles: wider against seats that fold too much, tighter against seats that rarely raise but have raised now, and so on.
- Correct behaviour under pot-limit, fixed-limit and a raise cap.
- Offline scripts in `tools/preflop/` that generate the tables. Only the finished tables are embedded in `src/preflop.py`.

**Inputs.**

- `state`: uses `hole_cards`, `seat`, `button`, `stacks`, `bets`, `folded`, `pot`, `to_call`, `min_raise_to`, `max_raise_to`, `legal_actions`, `big_blind`, `betting`, `raise_cap`, `raises_this_street` and `history`.
- `profiles`: the per-seat dict defined above.
- `common.position` and the shared constants.

**Outputs.**

- `preflop.decide(state, profiles) -> action`. Called only when `state["street"] == "preflop"`. It always returns an action dict, never `None`, and never raises an exception for any valid `state`.
- `preflop.hand_class(hole_cards) -> str`: the canonical name of a starting hand, for example `"AKs"`, `"AKo"` or `"TT"`. Marco and David use this so that all modules name hands the same way.
- `preflop.hand_strength(hole_cards) -> float` between 0 and 1, the hand's rank among the 169, for use by the other modules.

**Done when.**

- Unit checks cover every situation in the list above, for both 7 and 8 seats and all three betting structures.
- Average time is within the budget, measured by the harness.
- With the starter bot's postflop logic unchanged, swapping in this module improves bb/100 against the house bots by more than the harness noise.

## Role 3 — Postflop strategy (Marco, Macro1027)

**Purpose.** Decide every action on the flop, turn and river. These are the largest pots, so mistakes here cost the most chips per hand.

**Expected work.**

- `src/handeval.py`: a fast evaluator for the best five-card hand from five, six or seven cards, written for speed in plain Python.
- Classification of our hand on the current board: made-hand category, how it ranks against the board (top pair, overpair, and so on), and draws (flush draw, open-ended or gutshot straight draw, overcards).
- Board texture: paired, suited, connected, and how much it favours the preflop raiser.
- An estimate of how often our hand wins against the opponents still in the pot. Full simulation does not fit in the time budget, so this comes from the classification plus precomputed tables generated offline in `tools/postflop/`.
- Decision rules: value bet, bluff or semi-bluff, check, call using pot odds, raise, or fold; with bet sizing relative to the pot and the number of opponents.
- Adjustments from opponent profiles: bluff more against seats with high `fold_to_bet`, value bet thinner against seats with high `showdown`, respect raises from seats with low `aggression`.
- Correct behaviour under pot-limit, fixed-limit and a raise cap.

**Inputs.**

- `state`: uses `hole_cards`, `board`, `street`, `seat`, `button`, `stacks`, `bets`, `folded`, `pot`, `to_call`, `min_raise_to`, `max_raise_to`, `legal_actions`, `big_blind`, `betting`, `raise_cap`, `raises_this_street` and `history`. The preflop part of `history` shows who raised before the flop.
- `profiles`: the per-seat dict defined above.
- `preflop.hand_class` and `preflop.hand_strength` from cntrlaltdlt, and `common.position`.

**Outputs.**

- `postflop.decide(state, profiles) -> action`. Called only when `state["street"]` is `flop`, `turn` or `river`. It always returns an action dict, never `None`, and never raises an exception for any valid `state`.
- `handeval.rank(cards) -> tuple`: takes a list of five to seven card strings such as `["As", "Kd", "7h", "2c", "Js"]` and returns a tuple that compares higher for a better hand. The first element is the category from 0 (high card) to 8 (straight flush). Equal hands return equal tuples.
- `handeval.describe(hole_cards, board) -> dict` with keys `category` (int 0–8), `made` (str such as `"top_pair"` or `"overpair"`), `flush_draw` (bool), `straight_draw` (`"none"`, `"gutshot"` or `"open_ended"`) and `overcards` (int). David uses this to label hands shown at showdown.

**Done when.**

- `handeval.rank` agrees with the kit's `engine/cards.py` on at least 100,000 random hands, including ties.
- Unit checks cover each street, facing a bet and not facing a bet, heads-up and multi-way, and all three betting structures.
- Average time is within the budget, measured by the harness.
- With the starter bot's preflop logic unchanged, swapping in this module improves bb/100 against the house bots by more than the harness noise.

## Role 4 — Opponent modelling and data (David, Davidlikestoprogram)

**Purpose.** Work out how each opponent plays within a round so the strategy modules can exploit them, and use real competition data to tell the team what actually wins.

**Expected work.**

- `src/opponents.py`: an `OpponentModel` that tracks every seat across the 1,000 hands of a round and turns the counts into the profile dict defined above.
- Sensible behaviour with little data: each statistic starts at the population default and moves toward the observed value as hands accumulate, so one unusual hand does not flip a seat's `style`.
- Classification of each seat into a `style` label with thresholds that are stable from hand to hand.
- `analysis/`: scripts that take the hand histories downloaded by `fetch_hands.py` and report where our bot wins and loses chips (by position, street, hand class and opponent), and how real opponents play.
- New gauntlet bots in `examples/` that imitate the opponent types seen in real rounds, so the harness tests against something closer to the field than the three house bots.
- After each round or batch of rounds, a short written note on the Issue: the two or three largest leaks and the most common opponent types.

**Inputs.**

- `info` from `on_table_start`: `seat`, `num_players`, `hands`, `starting_stack`, `small_blind`, `big_blind`, `betting`, `raise_cap`.
- `summary` from `on_hand_end`: `hand_number`, `board`, `shown` (hole cards of seats that reached showdown, keyed by seat as a string), `winners`, `stacks` and the hand's full `history`.
- `handeval.describe` and `preflop.hand_class` to label hands that were shown.
- Downloaded hand histories. The data token is passed on the command line and is never committed.

**Outputs.**

- `OpponentModel()` with three methods:
  - `start(info) -> None`: called once per round.
  - `observe(summary) -> None`: called after every hand. It never raises an exception; a malformed summary is skipped.
  - `profiles() -> dict`: the per-seat dict defined above, with an entry for every seat from the first hand onward.
- Population defaults for `common.DEFAULT_PROFILE`, first as estimates and then measured from real rounds, handed to Zhanran.
- Gauntlet bots in `examples/`, each a single file following the same rules as `bot.py`.
- Analysis reports as text or CSV under `analysis/out/`, which is not committed if it contains the data token or raw downloads.

**Done when.**

- Replaying a recorded round through `OpponentModel` gives the same statistics as counting them by hand for at least three seats.
- Against the three house bots, each seat's `style` settles on the expected label within 100 hands.
- `observe` and `profiles` are within the time budget, measured by the harness.
- The first analysis note is on the Issue before the counted rounds start at 3:00 p.m.

## Working order

1. Zhanran merges `build.py`, `src/common.py`, the `Agent` wrapper and stub versions of the three modules that reproduce the starter bot. After this, everyone builds against a working whole.
2. Each owner replaces their stub on their own branch and opens a PR when the harness shows an improvement. The function signatures above do not change without the process in `docs/INTERFACES.md`.
3. Zhanran merges one PR at a time, rebuilds, runs the gate and decides whether to upload.
4. During counted rounds, only versions that beat the current upload in the harness by more than the noise are uploaded.

## Kickoff decisions

- Intended user and problem: win the AlgoSoc Pokerbots competition on bb/100.
- One core demo journey and acceptance criteria: a generated `bot.py` that plays full rounds with zero timeouts, errors and bank-outs and a positive bb/100 against the gauntlet.
- Non-goals / scope limit: no changes to `engine/`; no third-party packages; no simulation or search at decision time that risks the time bank.
- Stack, runtime versions and package manager: Python standard library only; the platform runs Python 3.12 and the kit needs 3.9 or later. No package manager.
- Installation, run and check commands: UNCONFIGURED in README.md until Role 1's first PR.
- Interface owners and canonical contracts: proposed in this file; UNCONFIGURED in docs/INTERFACES.md until the lead registers them.
- Deployment target and deployment operator: upload of `bot.py` on the competition's AI Poker Bots page, by the integration lead.
- Delivery policy: feature branch -> PR -> main -> verify -> deploy. GitHub Releases and release tags are not required for this event.

## Start gate

Before concurrent dependent feature implementation: agree the decisions above, assign the backup, merge a runnable skeleton, verify setup on teammates' machines, and give each ready Issue an owner, paths, dependencies and acceptance criteria. Everyone explicitly supplies AGENTS.md to their chosen agent and acknowledges the protocol on their first task.

## Where work lives

GitHub Issues hold individual tasks and blockers. PRs hold handoff evidence and merge decisions. This file is not a live task board. The lead consolidates product/role changes here through a PR.
