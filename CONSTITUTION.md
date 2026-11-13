# Team engineering constitution

Version 1 — 13 November 2026. Technology-neutral preparation for a four-person team.

## 1. Purpose

Deliver one coherent, demonstrable product while four humans and their chosen agents work independently. Prefer small working increments, explicit ownership and evidence over coordination overhead.

## 2. Shared authority

- Each task has one human owner accountable for their agents' output.
- Each integration shift has one human lead and a named backup. The lead can also build features. They coordinate shared files, interface decisions and the merge queue; they do not control others' choice of tools.
- Record the active lead and backup in PROJECT.md. Handing over requires both people to acknowledge the handover, update that record and identify any PR currently under review. Never have two active merge operators.
- Before assigning work, the lead checks for overlapping paths and contracts. Scope ownership is an explicit coordination agreement, not a distributed file lock.
- Every member may propose changes or challenge a decision. Product scope is a human team decision. The lead resolves sequencing; an unresolved semantic dispute remains blocked for the affected task while other work continues.

## 3. Sources of truth

| Information | Authoritative location | Writer |
| --- | --- | --- |
| Engineering principles | This file | Change through a reviewed PR |
| Agent behavior / Git procedure | AGENTS.md / WORKFLOW.md | Change through a reviewed PR |
| Product goal, role roster, kickoff choices | PROJECT.md | Integration lead consolidates agreed changes |
| Task scope, owner, status, blockers | One GitHub Issue per task | Task owner; lead confirms assignments/scope changes |
| Interface definition | Contract path recorded in docs/INTERFACES.md | Named contract owner |
| Architectural decisions | docs/DECISIONS.md | Lead records affected owners' agreement |
| Review, evidence, integration order | Pull request | Author and integration lead |

Within project policy, this constitution governs workflow documents and task instructions. A task may narrow scope but may not silently waive shared rules. Discuss contradictions before the affected write. Personal chat is not a replacement for recorded team decisions.

## 4. Ownership and isolation

- One task, one accountable owner, one branch, one PR; split large work into independently verifiable slices.
- One writer per checkout and branch. Parallel editing uses isolated checkouts/worktrees, even on the same laptop.
- Feature owners may change agreed feature paths. Shared files need a named owner and sequencing agreed before edits begin.
- Read access across modules is encouraged. No ownership rule prevents review or understanding the whole system.

## 5. Contract before coupling

Agree inputs, outputs, errors and observable behavior before parallel producer/consumer work. Record examples and a verification plan. Consumers must not infer a new contract from an agent's guess. See docs/INTERFACES.md for changes, mocks and breaking changes.

## 6. Main is the integrated product

- Main is intended to be runnable and suitable for the core demo after application bootstrap. Today's documentation-only repository is not a running application.
- Task owners push branches. Only the active integration lead/delegated agent merges ready PRs, one at a time.
- Every merge is checked against the current main and current PR head. A green check on an older combination is insufficient.
- Fix or revert a main-breaking change before merging unrelated features. Retain history; do not force-reset main.

## 7. Evidence and honest status

Report the exact code tested, commands, results and untested paths. Documentation checks do not establish application correctness. Until real build/test commands exist, application readiness is UNCONFIGURED, not PASS. Do not expose secrets in logs, Issues or PRs.

## 8. Change the rules explicitly

Any member may propose an amendment in a PR. The lead and affected human owners acknowledge it before adoption. A temporary exception states the rule, reason, limited scope, approver and expiry in the PR; it does not silently become a permanent rule. Safety constraints, truthful reporting and preservation of others' work are never waived.

## 9. Enforcement and bootstrap

These are operating agreements. AGENTS.md and reviewer lists are not access controls. On 13 November 2026 GitHub returned HTTP 403 for main branch protection: the current private repository requires an eligible paid plan for that feature. No platform-enforced review/check gate has been established. Collaborators technically retain write access; the team must follow the single-merge-operator agreement.

The initial documentation framework may be published by lizhanran2008's delegated agent under the repository owner's explicit setup request, through a bootstrap branch and PR with documented verification. This exception ends with that PR. Each teammate acknowledges the protocol before their first assigned implementation task. Normal work then follows the rules above.
