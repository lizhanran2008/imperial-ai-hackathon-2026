# Interface and shared-file protocol

## Contract registry

No application interfaces exist yet. At kickoff, the integration lead adds a row for every cross-module boundary before assigning dependent implementation.

| Contract / canonical path | Human owner | Producers / consumers | Status / compatibility |
| --- | --- | --- | --- |
| Not selected yet | TBD | TBD | UNCONFIGURED |

Once the stack is chosen, prefer one machine-readable canonical schema/type/API specification per boundary. Link it here; do not maintain competing definitions in multiple documents or invent a schema language in advance.

## What every contract specifies

- Purpose, owner and affected producer/consumer tasks.
- Input and output fields/types; required vs optional; missing vs null; units and IDs where relevant.
- At least one valid request/result and one error example, without real secrets or personal data.
- Error semantics and relevant behavior: timeouts/retries, async status, ordering, pagination or idempotency only where needed.
- Compatibility expectations and a concrete contract check. Mock fixtures use the same schema; mock-only verification is not evidence of real integration.

Agree the contract in a small PR, then implement producers and consumers against that merged definition. If a task depends on an unmerged change, mark the dependency and keep its PR draft until the dependency is integrated.

## Changing a contract

1. Open or update the task Issue with the proposed change, affected consumers and compatibility impact.
2. Contract owner and affected human owners acknowledge the new behavior. The lead sequences the work and records consequential decisions in DECISIONS.md.
3. Prefer an additive compatible change: add support first, migrate consumers, remove old behavior only after affected consumers are updated.
4. If a small breaking change must land atomically, create one coordinated integration task/PR covering producer, consumers, fixtures and tests. Original task owners contribute through explicit handoffs. Main must not pass through a knowingly incompatible intermediate state.
5. Update the canonical contract, examples and checks in the same change. Mention it in the PR and notify affected tasks. Revalidate consumers against the merged result.

## Shared-file coordination

Before editing a shared file, the lead assigns one writer and lists dependent tasks. Typical shared files: package manifests/lockfiles, shared schema/types, top-level routes, CI/build configuration, environment conventions and migrations. During setup, the lead coordinates all shared paths until actual owners are recorded below.

| Shared path/group | Assigned owner | Change rule |
| --- | --- | --- |
| Governance docs and templates | Integration lead | PR; affected owners acknowledge changes |
| Application shared paths | TBD at kickoff | Assign before first concurrent implementation |

Adding a dependency requires its purpose and affected commands in the task/PR. Use the agreed package manager to regenerate its lockfile; do not hand-splice conflicting lockfiles. Migrations require an explicit order and a data-preservation/recovery plan proportionate to the change.
