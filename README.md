# FisherMen: a poker bot for the AlgoSoc Pokerbots competition

FisherMen is a Python bot that plays No-Limit Texas Hold'em against other bots. We are a team of four and built it for the 14 November 2026 Imperial AI Hackathon, where we came **2nd out of 40+ teams**.

This page explains what the bot is for, the poker principles its code follows and how to run it. If you are here to contribute, start at [Working in this repository](#working-in-this-repository).

## Team

- ♠️ [Anant Jain](https://www.linkedin.com/in/j-anant/) — preflop strategy, adapting decisions to opponents' behaviour, and driving the final tournament iterations.
- ♥️ [Marco Lee](https://www.linkedin.com/in/marcolee27/) — hand evaluation and the postflop engine, estimating opponents' possible hands and evaluating actions within the time budget.
- ♦️ [David Sun](https://www.linkedin.com/in/david-sun-imperial/) — opponent tracking and profiling, plus the analytics tools that helped us investigate match histories.
- ♣️ Jerome Li — integration and evaluation, helping our separately developed components work together and figuring out which changes we could trust.

## Goals

The competition is No-Limit Texas Hold'em at tables of seven or eight bots. A round is 1,000 hands against the same opponents, every hand starts each bot on 100 big blinds, and bots are ranked by big blinds won per 100 hands (bb/100).

1. **Win the most chips per hand.** Every hand of a counted round goes into the ranking, so the bot is built to earn steadily over thousands of hands, not to win any one pot.
2. **Adapt to opponents it has never met.** Nothing carries over between rounds. The bot has to play soundly against strangers from the first hand, and better against each seat as it learns how that seat plays.
3. **Lose nothing to failures.** The bot has 10 ms for each decision and 10 s of thinking time for a whole round. A late answer or a crash is played for it as a check or a fold, which gives chips away whatever the strategy is. Every build has to finish its rounds with zero timeouts, zero errors and thinking time to spare.

## Poker principles

These are the ideas the bot is built on. The rules and numbers that carry them out change from version to version and live in the code, not on this page.

1. **An opponent is a range of hands.** The bot does not guess one hand for an opponent. For each seat still in the pot it keeps every hand that seat could hold, each with a weight, starting from how the seat entered the pot. Every check, bet, call or raise moves the weights toward the hands that would play that way.
2. **Expected chips decide.** Each option is scored by the chips it should win on average against those ranges: how often the opponents fold, and how often the hand wins when they do not. The bot takes the best-scoring option. A call has to win often enough to pay for its price, with a wider margin when more cards are to come, more players can still act or the bot will have to act first.
3. **Position is worth chips.** Acting after an opponent means seeing what they do first. The bot plays more hands from the late seats than from the early ones, and it values a hand lower when it will act first in the later betting rounds. First into a pot, it prefers a raise to a call, because a raise can win the pot at once.
4. **Play the seats at the table.** Every seat starts as an average player. The bot counts what each seat does: how often it enters pots, raises, folds to a bet, and turns out to have been bluffing when its cards are shown. Each estimate moves from the average toward that seat's own record as hands add up, so one unusual hand changes little. The bot then takes more pots from seats that fold, bets bigger with strong hands against seats that call, and calls more against seats that bet too often.
5. **Bet for value, bluff where it works.** With a strong hand the bot bets an amount that weaker hands will still call. It bluffs a limited share of the time, most readily with hands that can still improve, and less as more players stay in the pot. It stops bluffing a seat that does not fold. Bet sizes are mixed so that the size of a bet does not give the hand away.
6. **Big pots need big hands.** Every hand starts on 100 big blinds, so one all-in pot can undo the gains of many ordinary ones. In real rounds, opponents who bet the pot or moved all-in held stronger hands than the estimate assumed. When a large part of the stack is at risk, the estimate alone is not enough: the hand itself must be near the top of what is possible.

## How we build it

1. **Always a legal answer, on time.** Before an action is returned it is checked against the betting rules in force, which the organisers can switch between no-limit, pot-limit and fixed-limit. Each decision has a time budget, and a simpler rule answers when the full calculation cannot finish inside it. An error while deciding becomes a check or a fold, not a crash.
2. **Changes need evidence.** A new version and the one it would replace each play the same deals, from the same seat, against the same opponents, and the difference is reported with a confidence interval. Hand histories from real rounds show where chips were lost. A rule added because of them names those rounds in a comment and has a test that pins the behaviour.
3. **Separate modules, one uploaded file.** The platform accepts a single file that imports only the Python standard library. Each of us owns one part: preflop play, postflop play with hand evaluation, the opponent model, or integration and evaluation. The parts meet at a small fixed interface, and a build step joins them into the uploaded `bot.py`. A new version of one part can replace the old one without rewriting the others.

## How the bot is put together

The code is in [`imperial-ai-hack-pokerbots-kit/`](imperial-ai-hack-pokerbots-kit/). The [README in that folder](imperial-ai-hack-pokerbots-kit/README.md) describes the bot itself: its modules, what happens on each decision, and how to build, run and test it. It also keeps the organisers' guide to the competition rules and the bot API.

In short, for each decision the opponent model gives its current picture of every seat, the preflop module decides before the flop and the postflop module after it, and the chosen action is made legal before it is returned. After each hand, the record of that hand is fed back so the picture of each seat can be updated. [PROJECT.md](PROJECT.md) has the module interface and the roles.

## Reproducible commands

| Operation | Exact command / prerequisites |
| --- | --- |
| Install | Python 3.9+ (platform runs 3.12); standard library only, no packages to install |
| Run | `python3 imperial-ai-hack-pokerbots-kit/local_sim.py` (default 5 rounds of 1,000 hands) |
| Check/build | `python3 imperial-ai-hack-pokerbots-kit/build.py` (checks static imports, enforces the 200 KB limit and verifies an isolated load before replacing `bot.py`) |
| Core demo smoke test | `python3 imperial-ai-hack-pokerbots-kit/local_sim.py --rounds 1 --hands 1000 --seed 1` (0 timeouts, 0 errors, 0 bank out) |

Build before running the smoke test so it covers the current sources. The generated file records a SHA-256 digest of the bundled sources so identical inputs rebuild to the same file across checkouts. Record the reviewed commit and artifact digest in the PR handoff.

The rule tests run with `cd imperial-ai-hack-pokerbots-kit && python3 -m unittest discover -s tests`.

## Working in this repository

### Read first

1. [CONSTITUTION.md](CONSTITUTION.md): ownership, authority and common rules.
2. [AGENTS.md](AGENTS.md): give this file to every agent before it writes code.
3. [WORKFLOW.md](WORKFLOW.md): task assignment, pull/push, review, merge and recovery.
4. [PROJECT.md](PROJECT.md): what the competition requires, who owns what and the contract between modules.
5. [Interface protocol](docs/INTERFACES.md) and [decision record](docs/DECISIONS.md).

Choose your own tools. Team members share project contracts and the delivery protocol; personal account connections and machine settings stay outside the repository.

### First task

Accept the collaborator invitation and clone the repository. Read the documents above, then use the GitHub Task Issue template to agree a task with the integration lead. A task has one owner, bounded paths and explicit acceptance steps. Push to its short branch and hand off via a PR; the lead integrates ready PRs serially.

Before asking for strategy PR review, run the [pre-PR self-test](imperial-ai-hack-pokerbots-kit/harness/README.md) and paste the result in your PR.

Keep competition credentials and hand-history data tokens out of the repository.

### Enforcement status

Current rules are team agreements. GitHub reported that branch protection requires a plan upgrade for this private repository; main is not technically protected. No application CI or automatic merge service is configured. The integration lead operates the merge queue manually through PRs.
