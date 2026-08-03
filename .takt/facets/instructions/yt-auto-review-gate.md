Read and reconcile every specialist report:

{report:architecture-review.md}

{report:ai-antipattern-review.md}

{report:coding-review.md}

{report:implementation-semantics-review.md}

{report:contract-lifecycle-review.md}

{report:robustness-review.md}

Adjudicate only their blocking findings. Set structured verdict to `approve` only when all reports contain sufficient evidence and no blocking finding remains; set `reject` when implementation fixes are required; set `replan` when a premise or accepted contract must change; otherwise set `abort`. Preserve each finding in the structured findings array.
