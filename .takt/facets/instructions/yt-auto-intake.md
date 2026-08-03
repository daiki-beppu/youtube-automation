Read the task, `CLAUDE.md`, and the nearest relevant docs/tests before deciding whether this lane can proceed.

Set the structured verdict to exactly one of:

- `ready`: the requested outcome, acceptance evidence, scope, and lane are concrete enough to act on.
- `blocked`: one missing user decision would materially change Done or the safe scope.
- `abort`: the task belongs to another lane, requires forbidden external/destructive action, or combines independently shippable changes.

Do not edit files, mutate the issue, or invent missing acceptance criteria. For `ready`, state the user-visible contract, explicit non-goals, relevant constraints, and verification evidence for downstream steps.
