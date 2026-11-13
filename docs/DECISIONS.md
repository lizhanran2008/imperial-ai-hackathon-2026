# Team decision record

Only durable decisions affecting multiple tasks belong here. Task progress stays in Issues; review evidence stays in PRs. The integration lead consolidates entries to avoid four concurrent edits.

## D001 — Preparation baseline (2026-11-13)

- Status: established by repository owner for setup; teammates acknowledge before implementation.
- Decision: one shared repository; independent task branches; one active integration lead; serial squash merges; tool choice belongs to each member.
- Reason: keep integration reproducible while permitting parallel feature development.
- Constraints: no product/stack has been chosen; no build/test runner is configured; server-side branch protection is unavailable on the current private-repository plan.
- Follow-up: assign runtime roles and real interfaces at kickoff; validate the workflow with the first small PR.

## New entry format

`D<number> — title / date / status`

Record the problem, chosen behavior, affected paths/contracts/tasks, acknowledged human owners, consequences and any superseded decision. For a temporary exception, include scope and expiry. Do not imply team agreement that has not been obtained.
