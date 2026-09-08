#!/usr/bin/env bash
# Run from the checkout's devShell. All arguments belong to pytest.
set -u

# Interactive diagnostics and informational commands need their original output.
for argument in "$@"; do
    case "$argument" in
        -h|--help|-V|--version|--pdb|--trace)
            exec uv run pytest "$@"
            ;;
    esac
done

log_file=$(mktemp "${TMPDIR:-/tmp}/pytest-quiet.XXXXXXXX") || exit 1
trap 'rm -f -- "$log_file"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
SECONDS=0

uv run pytest "$@" >"$log_file" 2>&1
pytest_status=$?
if [ "$pytest_status" -eq 0 ]; then
    printf 'pytest: success (exit 0, %ss)\n' "$SECONDS"
else
    cat -- "$log_file"
fi
exit "$pytest_status"
