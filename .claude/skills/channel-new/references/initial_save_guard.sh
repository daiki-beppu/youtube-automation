#!/usr/bin/env bash
set -euo pipefail

staged_secret_paths=()

while IFS= read -r path; do
  if [[ "$path" =~ (^|/)(client_secrets|token)\.json$ || "$path" =~ (^|/)\.env$ ]]; then
    staged_secret_paths+=("$path")
  fi
done < <(git diff --cached --name-only)

if ((${#staged_secret_paths[@]} > 0)); then
  {
    echo "secret-like file staged; unstage before commit:"
    printf '  %s\n' "${staged_secret_paths[@]}"
    echo "Run: git restore --staged -- <path>"
  } >&2
  exit 1
fi
