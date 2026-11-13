# Imperial AI Hackathon — team workspace

Preparation for 14 November 2026. No application or technology stack has been selected yet.

## Read first

1. [CONSTITUTION.md](CONSTITUTION.md): ownership, authority and common rules.
2. [AGENTS.md](AGENTS.md): give this file to every agent before it writes code.
3. [WORKFLOW.md](WORKFLOW.md): task assignment, pull/push, review, merge and recovery.
4. [PROJECT.md](PROJECT.md): product alignment, role roster and kickoff gate.
5. [Interface protocol](docs/INTERFACES.md) and [decision record](docs/DECISIONS.md).

Choose your own tools. Team members share project contracts and the delivery protocol; personal account connections and machine settings stay outside the repository.

## First task

Accept the collaborator invitation and clone the repository. Read the documents above, then use the GitHub Task Issue template to agree a task with the integration lead. A task has one owner, bounded paths and explicit acceptance steps. Push to its short branch and hand off via a PR; the lead integrates ready PRs serially.

## Reproducible commands — UNCONFIGURED

| Operation | Exact command / prerequisites |
| --- | --- |
| Install | TBD after stack and versions are chosen |
| Run | TBD |
| Check/build | TBD; must fail visibly on errors |
| Core demo smoke test | TBD; include expected result |

The skeleton task must replace these entries with tested commands and configure corresponding PR checks when appropriate. Until then, documentation validation is the only available validation; it does not establish build readiness. No placeholder workflow reports a fake green build.

Once integrations are chosen, commit `.env.example` with variable names and dummy values only. Keep real credentials and local environment files untracked.

## Enforcement status

Current rules are team agreements. GitHub reported that branch protection requires a plan upgrade for this private repository; main is not technically protected. No application CI or automatic merge service is configured. The integration lead operates the merge queue manually through PRs.
