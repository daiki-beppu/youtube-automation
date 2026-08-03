Act as a read-only CI-equivalent delivery gate. Inspect `.github/workflows/ci.yml` and the changed paths, then run every applicable local gate. The mandatory baseline is:

```bash
nix develop --command uv run ruff check .
nix develop --command uv run ruff format --check .
nix develop --command uv run pytest -n auto
bash .github/scripts/any-usage-gate.sh
git diff --check
```

Also run applicable packaging, frontend/extension, ADR, skill, and CHANGELOG checks selected by the CI path contract. Never edit files, skip tests, narrow scope, or reinterpret a failed command as success.

Set structured verdict to `pass` only when all applicable commands exited zero and name every command/result. Set `fail` for a product/test/docs defect, or `abort` when an unavailable tool or environment prevents an honest verdict.
