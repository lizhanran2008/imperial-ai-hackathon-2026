# Working and integration protocol

## 1. Align, then assign

At kickoff agree the demo journey, stack, shared contracts, lead and backup in PROJECT.md. The lead publishes a runnable skeleton and actual setup/check commands before dependent feature implementation starts. Independent research or design can proceed earlier as explicit tasks.

Use the Task Issue template. The lead assigns one owner and confirms allowed paths, dependencies and acceptance criteria. Two tasks touching shared files must have an explicit order or a separate shared-change task. Do not treat simultaneous self-assignment as a lock.

States are written on the Issue: `proposed -> ready -> active -> review -> integrated`. `blocked` may interrupt any stage. The lead confirms ready; the owner reports active/review/blocked; merge closes the Issue. No project board, labels or bots are required.

## 2. Start and pull

Check for uncommitted work before switching branches. Commit it to its rightful task or coordinate with its owner; never stash/reset someone else's work automatically.

```sh
git status --short --branch
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c feat/123-short-description
```

Replace 123 with the Issue number. If local main has unexpected commits or cannot fast-forward, stop and inspect; do not force it into place. Record the starting main SHA on the task.

While on a task branch, integrate updates explicitly after committing your own work:

```sh
git fetch origin
git merge origin/main
```

Pull at task start, before handoff and after a relevant interface update. Do not run blind pulls in a dirty/shared checkout. Published task branches use ordinary merge updates, not force-pushed rebases. Never merge another unfinished feature branch ad hoc; declare the dependency and let the lead order the PRs.

## 3. Push and handoff

Inspect git diff and stage named files. Commit small coherent changes, then `git push -u origin <task-branch>`. Draft PRs can expose early work; mark ready only after the acceptance steps are reproducible. Link the Issue and complete the PR template.

Handoff identifies head SHA, tested main SHA, checks/results, shared interface changes and limitations. A ready PR is frozen during review. To edit again, notify the lead, return it to draft and repeat verification after the new commit. Push success means uploaded, not accepted or integrated.

## 4. Serial integration — lead only

1. Select one ready PR whose dependencies are already merged. State on the PR that review has started; other ready PRs remain queued. Use dependency order first, then oldest ready work. Record any reprioritization.
2. Fetch current main and PR head. Review the full diff for task scope, contracts, shared files and acceptance behavior in an isolated clean checkout/worktree.
3. Ensure current main is included in the tested branch. If not, return it to the owner to merge origin/main and resolve conflicts, or explicitly accept branch-write ownership while the owner pauses. Re-run checks afterward.
4. Run README's real check/build commands and the task's acceptance checks on that combined state. Inspect hosted checks if configured. Application PRs need application evidence; documentation-only PRs use documentation validation.
5. Record the tested main SHA and head SHA, results and decision on the PR. Re-read both remote SHAs immediately before merge. If either moved, repeat the relevant review/tests. Merge using the exact reviewed head SHA where the client supports it.
6. Squash-merge that PR only. Start no second merge until the resulting main passes the core smoke/demo check. If it fails, follow recovery below.
7. Notify affected owners through the PR/Issue. Their next tasks start from updated main. A merged branch is never reused; retain it until its owner confirms no unmerged work remains.

Without server-enforced protection, human coordination is still necessary to prevent a concurrent direct push during the final check/merge window. A matching-head option protects the PR head, not an independently moving base branch.

## 5. Conflicts and recovery

- Mechanical conflicts may be fixed by the agreed writer. Changes to behavior, schema, data meaning or API semantics require the affected owner's confirmation. Never resolve by discarding a feature or blindly selecting ours/theirs.
- If main breaks, pause unrelated merges. The lead chooses a small verified fix or a revert PR for the faulty squash commit, then verifies main again. Do not rewrite shared history.
- Interface-breaking changes follow docs/INTERFACES.md. The lead checks dependent tasks before merging.
- Delivery for this event is task branch -> PR -> main -> verify -> deploy. Do not create GitHub Releases or release tags as part of the normal workflow.
- Before deployment/demo, the lead announces a short freeze, records the known-good main SHA and verifies the demo. Only targeted fixes enter during that freeze. Deploy that exact verified main revision and record the deployed SHA and outcome in the PR or deployment record. A merge alone does not prove deployment succeeded.

## 6. Alignment and operator handover

At task start, contract/scope changes, ready-for-review and blockers, record the change on the relevant Issue/PR. Roughly hourly, humans briefly review what merged, what is blocked and which interface changed; no long status report is required.

For agent or human replacement, leave: Issue, branch/head, base main SHA, dirty files, allowed paths, contract versions/paths, checks, blockers and next action. The old writer pauses; the new writer acknowledges before editing. Updating a chat alone does not transfer ownership.
