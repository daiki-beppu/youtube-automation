#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SUMMARY_PATH="${GITHUB_STEP_SUMMARY:?GITHUB_STEP_SUMMARY is required}"
AGENT="${YTA_AGENT:?YTA_AGENT is required}"

report_rotation() {
  {
    printf '## YouTube automation stopped\n\n'
    printf 'The headless agent did not start or complete. No workflow retry was attempted.\n\n'
    printf 'If the job log reports authentication failure, follow the subscription OAuth rotation runbook and replace `CLAUDE_CODE_OAUTH_TOKEN` before re-running this workflow.\n'
  } >>"$SUMMARY_PATH"
}

if [[ "$AGENT" == "claude" && -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  report_rotation
  printf 'CLAUDE_CODE_OAUTH_TOKEN is required for the Claude headless runner\n' >&2
  exit 78
fi

bash "$SCRIPT_DIR/run-sandwich.sh" "$@"
status=$?
if (( status != 0 )); then
  report_rotation
fi
exit "$status"
