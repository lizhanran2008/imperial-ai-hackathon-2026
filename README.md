# Imperial AI Hackathon — team workspace

Team workspace for the 14 November 2026 Imperial AI Hackathon. The team is building a Python bot for the AlgoSoc Pokerbots competition.

## Read first

1. [CONSTITUTION.md](CONSTITUTION.md): ownership, authority and common rules.
2. [AGENTS.md](AGENTS.md): give this file to every agent before it writes code.
3. [WORKFLOW.md](WORKFLOW.md): task assignment, pull/push, review, merge and recovery.
4. [PROJECT.md](PROJECT.md): product alignment, role roster and kickoff gate.
5. [Interface protocol](docs/INTERFACES.md) and [decision record](docs/DECISIONS.md).

Choose your own tools. Team members share project contracts and the delivery protocol; personal account connections and machine settings stay outside the repository.

## First task

Accept the collaborator invitation and clone the repository. Read the documents above, then use the GitHub Task Issue template to agree a task with the integration lead. A task has one owner, bounded paths and explicit acceptance steps. Push to its short branch and hand off via a PR; the lead integrates ready PRs serially.

## Reproducible commands

| Operation | Exact command / prerequisites |
| --- | --- |
| Install | Python 3.9+ (platform runs 3.12); standard library only, no packages to install |
| Run | `python3 imperial-ai-hack-pokerbots-kit/local_sim.py` (default 5 rounds of 1,000 hands) |
| Check/build | `python3 imperial-ai-hack-pokerbots-kit/build.py` (checks static imports, enforces the 200 KB limit and verifies an isolated load before replacing `bot.py`) |
| Core demo smoke test | `python3 imperial-ai-hack-pokerbots-kit/local_sim.py --rounds 1 --hands 1000 --seed 1` (0 timeouts, 0 errors, 0 bank out) |

Build before running the smoke test so it covers the current sources. The generated file records a SHA-256 digest of the bundled sources so identical inputs rebuild to the same file across checkouts. Record the reviewed commit and artifact digest in the PR handoff.

Keep competition credentials and hand-history data tokens out of the repository.

## Enforcement status

Current rules are team agreements. GitHub reported that branch protection requires a plan upgrade for this private repository; main is not technically protected. No application CI or automatic merge service is configured. The integration lead operates the merge queue manually through PRs.

