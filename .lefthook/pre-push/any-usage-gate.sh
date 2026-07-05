#!/usr/bin/env bash
#
# 新規追加行の広すぎる Any / any 型注釈を検出する。
#
# 判定基準: origin/main からの分岐点（merge-base）と現在の HEAD の差分。

set -euo pipefail

BASE_REF="origin/main"
if ! git rev-parse --verify --quiet "${BASE_REF}^{commit}" >/dev/null; then
  echo "any-usage-gate: ${BASE_REF} が無いためスキップします（CI / review で確認してください）。" >&2
  exit 0
fi

if ! diff_base=$(git merge-base "${BASE_REF}" HEAD 2>/dev/null); then
  diff_base="${BASE_REF}"
fi

current_file=""
current_line=0
violations=()
python_any_pattern='typing[.]Any'
typescript_any_pattern=':[[:space:]]any([^[:alnum:]_]|$)'
diff_output=$(git diff --unified=0 --no-color "${diff_base}" HEAD -- 2>/dev/null || true)

[ -z "${diff_output}" ] && exit 0

while IFS= read -r line; do
  case "${line}" in
    "+++ b/"*)
      current_file="${line#+++ b/}"
      current_line=0
      continue
      ;;
    "@@ "*)
      if [[ "${line}" =~ \+([0-9]+)(,([0-9]+))? ]]; then
        current_line="${BASH_REMATCH[1]}"
      fi
      continue
      ;;
  esac

  [[ "${line}" == +* ]] || continue
  [[ "${line}" == "+++"* ]] && continue

  case "${current_file}" in
    src/youtube_automation/*.py|tests/*.py|extensions/*.ts|extensions/*.tsx|packages/*.ts|packages/*.tsx)
      ;;
    *)
      if [ "${current_line}" -gt 0 ]; then
        current_line=$((current_line + 1))
      fi
      continue
      ;;
  esac

  added="${line#+}"
  if [[ "${added}" =~ ${python_any_pattern} ]] || [[ "${added}" =~ ${typescript_any_pattern} ]]; then
    violations+=("${current_file}:${current_line}: ${added}")
  fi

  if [ "${current_line}" -gt 0 ]; then
    current_line=$((current_line + 1))
  fi
done <<EOF
${diff_output}
EOF

if [ "${#violations[@]}" -gt 0 ]; then
  policy_python_token="typing"".Any"
  policy_ts_token=": ""any"
  echo "" >&2
  echo "any-usage-gate: ERROR: 新規追加行に ${policy_python_token} / ${policy_ts_token} が含まれています。" >&2
  echo "  レビューポリシー: 提出前セルフ監査チェックリストの機械チェックで REJECT 条件です。" >&2
  echo "  型を具体化するか、設計判断が必要な場合は実装を止めて報告してください。" >&2
  echo "" >&2
  printf '  %s\n' "${violations[@]}" >&2
  echo "" >&2
  exit 1
fi

exit 0
