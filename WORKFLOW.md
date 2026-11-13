# Team workflow

## Four builders, one integration owner

Everyone owns a complete user-visible feature. One member also handles the merge queue and deployment. Assign that person in PROJECT.md before parallel coding starts.

Use `main` for the working demo and short branches such as `feat/jerome-input` or `fix/david-upload`. No separate develop branch is needed.

## Working cycle

1. Claim a task in PROJECT.md; name affected shared files before editing them.
2. Start from current main with a clean working tree:

```sh
git switch main
git pull --ff-only
git switch -c feat/yourname-feature
```

3. Implement one small working slice and run the relevant checks.
4. Review `git diff` and stage only intended files, then commit and push your branch.
5. Open a PR using the short template. The integration owner checks it against current main, merges, and runs the main demo journey.
6. After a squash merge, start the next task on a fresh branch from updated main. Do not reuse the old feature branch.

Aim to integrate every working slice; review progress roughly hourly. Avoid leaving all merges until the final hour. If main breaks, fix it immediately or revert the specific faulty change.

## Working with your tools

Each teammate chooses their own tools and working style. Hand off a stable branch/commit, a short description of the change and verification results for review.

If multiple tools edit code concurrently, use separate checkouts and branches to avoid overwriting changes. Coding agents should read AGENTS.md, PROJECT.md and this file. Record shared decisions in the repo.

## Shared-file ownership

Coordinate changes to dependencies/lockfiles, routing, shared types, database migrations and environment configuration with the integration owner. Ordinary feature directories need no extra ceremony.

## Merge gate

- App starts and the core demo works.
- Relevant checks pass, with failures explicitly recorded.
- No real secrets are committed.
- API/data-format changes are mentioned and dependent features still work.

Keep PRs small. One human integration owner makes the final merge decision; AI assists with review and fixes. Invite team collaborators after confirming repository ownership and access.
