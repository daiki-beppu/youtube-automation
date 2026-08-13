Act as a read-only CI-equivalent delivery gate. Inspect `.github/workflows/ci.yml` and the changed paths, then run every applicable local gate. The mandatory baseline is:

```bash
nix develop --command uv run ruff check .
nix develop --command uv run ruff format --check .
python .github/scripts/run-affected-tests.py
bash .github/scripts/any-usage-gate.sh
git diff --check
```

The affected-test runner collects committed, staged, unstaged, and untracked worktree paths, applies the same selector as pull-request CI, reports selected/total target counts, and runs the exact full `pytest -n auto` suite when the plan is `ALL`. This dependency-based selection is the required CI contract, not permission to manually skip tests, narrow scope, add marker filters, or omit a target. The unselected surface remains protected by the exact full suite on CI's `main` push.

Also run applicable packaging, frontend/extension, ADR, skill, and CHANGELOG checks selected by the CI path contract. Never edit files, skip tests, narrow scope, or reinterpret a failed command as success.

The structured verdict has exactly two outcomes: `pass` or `fail`. Set `pass` only when every locally runnable applicable command exited zero, and name every command/result. Set `fail` when a locally runnable gate exposes a product/test/docs defect so the workflow routes to `fix`. Never return `abort` from `ci_verify`.

When an applicable gate cannot run locally because the measured environment lacks its command or cannot resolve a required resource, classify that gate as **CI-only** and exclude it from the local verdict. In `findings`, list every excluded gate by name together with the observed reason it was unavailable. Do not silently skip it or treat attempted execution as success. CI-only is permitted only after observing the unavailable command or resource; never use it to avoid a runnable test. The authoritative CI remains responsible for every CI-only gate.
