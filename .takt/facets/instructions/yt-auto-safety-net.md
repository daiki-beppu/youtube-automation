Before refactoring, add or identify tests that pin the behavior-preservation contract. Run them against the unrefactored code and record the green baseline. Do not alter production behavior or weaken existing checks.

Set structured verdict to `baseline_ready` only when the preservation contract is executable and green, `replan` when the plan cannot be guarded, or `out_of_lane` when a behavior change is required.
