Extend the existing audit ledger; never replace it with a summary or delete prior entries. Inspect the next bounded batch, append evidence and verdicts, update exact completed/total counts, and preserve every existing finding ID. Do not edit product files.

Set structured verdict to `scope_complete` only when every planned target has evidence and a verdict, `progressed` when counts increased but work remains, or `abort` when evidence cannot be obtained.
