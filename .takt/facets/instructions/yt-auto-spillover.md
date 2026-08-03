Review the run reports under `{report_dir}` for discoveries outside the accepted scope. Do not edit repository files. Classify each discovery as causal (must return to the lane), actionable non-causal (record a manual issue draft only), or unsupported/non-actionable (discard with reason).

This step must not call `gh`, create issues, comment, push, or open a PR; external delivery remains a human/auto_pr action. Set structured verdict to `return` when a causal finding belongs in this change, otherwise `complete`. Include a concise ledger even when there are no findings.
