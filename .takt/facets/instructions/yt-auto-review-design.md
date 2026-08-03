Review the proposed plan and test design before implementation. Check that every user-visible requirement has a falsifiable check, repository boundaries and existing contracts are respected, and the design is the smallest coherent change.

Return exactly one verdict:

- `APPROVE`: implementation can begin without unresolved correctness risk.
- `REJECT`: the design is repairable without changing the task contract; list concrete blocking findings.
- `NEED_REPLAN`: a premise, scope boundary, or acceptance contract must be reconsidered.

This is read-only. Missing evidence fails closed; do not approve based on expected future work.
