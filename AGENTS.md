# Agent operating contract

Applies to every coding agent in this repository, regardless of vendor or editor. Humans must explicitly give agents this file when their tool does not auto-load it. These are project collaboration rules, not permission to access unrelated accounts or bypass tool security.

## Before writing

1. Read `CONSTITUTION.md`, `WORKFLOW.md`, `PROJECT.md`, `docs/INTERFACES.md` and relevant decisions in `docs/DECISIONS.md`.
2. Read the assigned GitHub Issue: one human owner, task scope, allowed paths, interface dependencies and acceptance criteria. Missing ownership or overlapping scope means ask the integration lead to resolve it before writing the affected files.
3. Inspect `git status`, current branch and current `origin/main`. Preserve existing work. Work on `feat/<issue>-<slug>`, `fix/<issue>-<slug>` or `docs/<issue>-<slug>`, never directly on main.
4. Acknowledge the task to your human: issue, branch, base main SHA, allowed paths, interfaces and check plan. Do not claim to have read files or run checks you did not inspect or execute.

## While working

- One writer per task branch and checkout. Multiple concurrent agents need separate branches and checkouts/worktrees plus explicit task boundaries.
- Stay within the assigned paths. Reading other modules is allowed; editing outside scope requires an Issue update acknowledged by the integration lead and affected owner.
- Do not silently change shared contracts, dependencies, lockfiles, top-level routing, CI, database migrations or environment conventions. Follow `docs/INTERFACES.md`.
- Keep real credentials and personal tool/account configuration out of tracked files. Example environment files contain names and dummy values only.
- Do not discard others' work, force-push, rewrite published history or resolve semantic conflicts by arbitrarily choosing one side.
- Update progress/blockers on the task Issue, not in a shared status document. Team chat is a notification channel; record binding decisions in the Issue/PR or decision log.

## Before handing off

- Fetch and merge current origin/main into your clean task branch. Run the project's documented checks and task acceptance steps on the resulting code.
- Inspect the complete diff, stage only intended files, commit and push your task branch. Use the PR template; include the exact head SHA and tested main SHA.
- Mark the PR ready only when the task can be evaluated. Freeze branch edits while the integration lead reviews it. New commits invalidate the handoff and require new evidence.
- Only the current integration lead, or its explicitly delegated agent, merges to main. Merely having GitHub write access is not merge authority under this protocol.
- After squash merge, start a new task from updated main. Never reuse the merged branch.

## When blocked

Describe the blocker, affected interface/files and smallest decision needed on the Issue. Continue independent in-scope work if possible. Do not invent product choices, API behavior, credentials or passing test results.

## Integration agent

Follow WORKFLOW.md's serial merge procedure. Verify current main and PR head, inspect the combined code, run checks and recheck both SHAs before merging. Never merge based on an old review after either SHA changes. Keep task owners responsible for semantic decisions.
