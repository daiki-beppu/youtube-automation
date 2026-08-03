Inspect the plan and append-only ledger:

{report:audit-plan.md}

{report:audit-ledger.md}

Verify physical target coverage, monotonic completed counts, stable finding IDs, evidence quality, and whether another bounded pass can make progress.

Set structured verdict to `approve` only for complete coverage, `rework` with uniquely identified missing evidence when progress remains possible, or `abort` for a stalled/repeated defect or broken ledger that cannot be recovered safely.
