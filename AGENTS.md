# Shared instructions for coding agents

- Read README.md, PROJECT.md and WORKFLOW.md before making changes.
- Work toward the agreed demo and assigned task. Stack and product scope are initially undecided; do not invent them.
- One writer per checkout. Inspect git status and branch before editing; preserve others' uncommitted changes.
- Use short task branches. Do not force-push shared branches, reset others' work, or silently remove features to resolve conflicts.
- Coordinate changes to shared interfaces, dependencies, lockfiles, routing and migrations with the integration owner.
- Prefer the smallest working vertical slice. Avoid broad refactors during the event.
- Never commit credentials or real .env files. Use dummy values in .env.example.
- Run the relevant checks and report exactly what was tested. Do not claim success from code inspection alone.
- Handoff format: branch and commit, user-visible change, files/interfaces changed, verification, remaining issues.
- Record durable decisions in PROJECT.md and accurate setup commands in README.md.
