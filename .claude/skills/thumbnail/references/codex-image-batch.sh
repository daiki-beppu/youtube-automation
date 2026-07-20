#!/usr/bin/env bash
# Usage: codex-image-batch.sh --manifest jobs.json [--max-parallel N]
# Manifest: [{"id":"v1","prompt":"...","output":"...png","reference":"...png"}, ...]
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
manifest=""
max_parallel=""
runner="$script_dir/codex-image.sh"

usage() {
  echo "usage: codex-image-batch.sh --manifest jobs.json [--max-parallel N]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --manifest)
      manifest=${2:?--manifest requires a path}
      shift 2
      ;;
    --max-parallel)
      max_parallel=${2:?--max-parallel requires an integer}
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [ -z "$manifest" ] || [ ! -f "$manifest" ]; then
  echo "ERROR: --manifest must point to an existing JSON file" >&2
  exit 1
fi
if [ ! -f "$runner" ]; then
  echo "ERROR: runner not found: $runner" >&2
  exit 1
fi
for command_name in codex jq uv; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: $command_name CLI が PATH にありません" >&2
    exit 1
  fi
done

# Validate the complete batch before authentication or side effects. IDs and outputs
# are unique so each single-image wrapper owns an independent stale/hash guard.
if ! jq -e '
  type == "array" and length >= 2 and
  all(.[];
    type == "object" and
    (.id | type == "string" and length > 0) and
    (.prompt | type == "string" and length > 0) and
    (.output | type == "string" and length > 0) and
    ((.reference // "") | type == "string")
  ) and
  ([.[].id] | length == (unique | length)) and
  ([.[].output] | length == (unique | length))
' "$manifest" >/dev/null; then
  echo "ERROR: manifest requires 2+ jobs with non-empty unique id/output and string prompt/reference" >&2
  exit 1
fi

# Lexically different paths can still point at the same file through symlinked
# parent directories. Resolve those aliases before any preflight or generation.
if ! uv run --no-sync python - "$manifest" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
jobs = json.loads(manifest_path.read_text(encoding="utf-8"))
outputs = []
for job in jobs:
    output = Path(job["output"]).expanduser()
    if not output.is_absolute():
        output = Path.cwd() / output
    outputs.append(output.resolve(strict=False))

if len(outputs) != len(set(outputs)):
    raise SystemExit("canonical output paths must be unique")
PY
then
  echo "ERROR: canonical output paths must be unique" >&2
  exit 1
fi

if [ -z "$max_parallel" ]; then
  # 通常の `uv run` で worktree-local .venv を lockfile へ同期する。環境を
  # 準備できない失敗と、準備後の thumbnail config 不備を別の診断にする。
  if ! uv run python - <<'PY'
from youtube_automation.utils.image_provider.config import parse_image_generation_config  # noqa: F401
from youtube_automation.utils.skill_config import load_skill_config  # noqa: F401
PY
  then
    echo "ERROR: thumbnail config を読む project 環境を準備できません" >&2
    echo "復旧: bash .lefthook/setup-worktree.sh <command> [args...]" >&2
    exit 1
  fi
  if ! max_parallel=$(uv run python - <<'PY'
import os
from pathlib import Path

from youtube_automation.utils.image_provider.config import parse_image_generation_config
from youtube_automation.utils.skill_config import load_skill_config

channel_root = Path(os.environ.get("CHANNEL_DIR", "."))
config = parse_image_generation_config(
    load_skill_config("thumbnail", use_cache=False, channel_dir=channel_root)
)
if config.codex is None:
    raise SystemExit("image_generation.provider must be codex")
print(config.codex.max_parallel)
PY
  ); then
    echo "ERROR: project 環境は準備済みですが image_generation.codex.max_parallel の設定を解決できません" >&2
    exit 1
  fi
fi
if ! [[ "$max_parallel" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: --max-parallel / image_generation.codex.max_parallel must be an integer >= 1" >&2
  exit 1
fi

real_codex=$(command -v codex)
if ! login_status=$($real_codex login status 2>&1); then
  echo "ERROR: codex login status の実行に失敗しました" >&2
  echo "$login_status" >&2
  exit 1
fi
if [[ "$login_status" != *"Logged in using ChatGPT"* ]]; then
  echo "ERROR: codex login status で Logged in using ChatGPT を確認してから再実行してください" >&2
  exit 1
fi

# Compatibility preflight is intentionally once per batch. Child codex-image.sh
# processes keep their single-image implementation unchanged and see a narrow PATH
# shim which only short-circuits checks already completed here.
if ! $real_codex exec --json --skip-git-repo-check -- "Reply with exactly codex-model-compat-ok." \
  </dev/null >/dev/null; then
  echo "ERROR: codex CLI とデフォルトモデルの互換性プリフライトに失敗しました" >&2
  exit 1
fi

tmp_root=$(mktemp -d "${TMPDIR:-/tmp}/codex-image-batch.XXXXXX")
trap 'rm -rf "$tmp_root"' EXIT
shim_dir="$tmp_root/bin"
mkdir -p "$shim_dir"
cat > "$shim_dir/codex" <<'SHIM'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "--version" ]; then
  exec "$CODEX_IMAGE_REAL_CODEX" --version
fi
if [ "${1:-}" = "login" ] && [ "${2:-}" = "status" ]; then
  echo "Logged in using ChatGPT"
  exit 0
fi
last=""
for arg in "$@"; do
  last=$arg
done
if [ "${1:-}" = "exec" ] && [ "$last" = "Reply with exactly codex-model-compat-ok." ]; then
  exit 0
fi
exec "$CODEX_IMAGE_REAL_CODEX" "$@"
SHIM
chmod +x "$shim_dir/codex"

job_lines="$tmp_root/jobs.jsonl"
jq -c '.[]' "$manifest" > "$job_lines"
failures="$tmp_root/failures.tsv"
: > "$failures"

group_pids=()
group_ids=()
group_prompts=()
group_logs=()

run_job() {
  local job=$1
  local prompt output reference
  prompt=$(jq -r '.prompt' <<< "$job")
  output=$(jq -r '.output' <<< "$job")
  reference=$(jq -r '.reference // empty' <<< "$job")
  if [ -n "$reference" ]; then
    CODEX_IMAGE_REAL_CODEX="$real_codex" PATH="$shim_dir:$PATH" \
      "$runner" --require-reference "$prompt" "$output" "$reference"
  else
    CODEX_IMAGE_REAL_CODEX="$real_codex" PATH="$shim_dir:$PATH" \
      "$runner" "$prompt" "$output"
  fi
}

wait_group() {
  local index rc
  for ((index = 0; index < ${#group_pids[@]}; index++)); do
    rc=0
    wait "${group_pids[$index]}" || rc=$?
    if [ -s "${group_logs[$index]}" ]; then
      cat "${group_logs[$index]}" >&2
    fi
    if [ "$rc" -ne 0 ]; then
      jq -nc \
        --arg id "${group_ids[$index]}" \
        --arg prompt "${group_prompts[$index]}" \
        --argjson exit "$rc" \
        '{id: $id, prompt: $prompt, exit: $exit}' >> "$failures"
    fi
  done
  group_pids=()
  group_ids=()
  group_prompts=()
  group_logs=()
}

job_index=0
while IFS= read -r job; do
  job_index=$((job_index + 1))
  id=$(jq -r '.id' <<< "$job")
  prompt=$(jq -r '.prompt' <<< "$job")
  log="$tmp_root/job-${job_index}.log"
  run_job "$job" >"$log" 2>&1 &
  group_pids+=("$!")
  group_ids+=("$id")
  group_prompts+=("$prompt")
  group_logs+=("$log")
  if [ "${#group_pids[@]}" -ge "$max_parallel" ]; then
    wait_group
  fi
done < "$job_lines"
if [ "${#group_pids[@]}" -gt 0 ]; then
  wait_group
fi

if [ -s "$failures" ]; then
  echo "ERROR: codex image batch failures (id, prompt, exit):" >&2
  while IFS= read -r failed_job; do
    failed_id=$(jq -r '.id | @json' <<< "$failed_job")
    failed_prompt=$(jq -r '.prompt | @json' <<< "$failed_job")
    failed_rc=$(jq -r '.exit' <<< "$failed_job")
    printf '  - id=%s prompt=%s (exit=%s)\n' "$failed_id" "$failed_prompt" "$failed_rc" >&2
  done < "$failures"
  exit 1
fi

echo "completed: $(jq 'length' "$manifest") images (max_parallel=$max_parallel)"
