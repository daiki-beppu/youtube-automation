#!/usr/bin/env bash
set -u

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  exit 0
fi

if ! command -v lefthook >/dev/null 2>&1; then
  echo "error: lefthook is not available in PATH; enter via nix develop or direnv." >&2
  exit 1
fi

if ! lefthook install --force; then
  echo "error: lefthook install failed; run 'nix develop --command lefthook install --force' after fixing the error." >&2
  exit 1
fi
