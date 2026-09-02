#!/usr/bin/env bash
set -o pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
LOG_PATH="${RUNNER_TEMP:?RUNNER_TEMP is required}/claude-output.log"

"${SCRIPT_DIR}/claude-native" --dangerously-skip-permissions "$@" 2>&1 | tee "$LOG_PATH"
