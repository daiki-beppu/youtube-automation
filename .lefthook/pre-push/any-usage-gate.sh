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
current_file_any_aliases=()
violations=()
python_any_pattern='typing[.]Any'
# TypeScript の any は型位置（: any, ジェネリック引数 <any>, union/intersection,
# tuple 要素）に限定して検出する。素の単語境界だけだと "any" を含む英語の
# コメントや文字列（"works for any input" 等）を誤検知するため、型を導入する
# 記号（: < , | & ( [）の直後という条件を必須にする。
typescript_any_pattern='(:|<|,|\||&|\(|\[)[[:space:]]*any([^A-Za-z0-9_$]|$)'
diff_output=$(git diff --unified=0 --no-color "${diff_base}" HEAD -- 2>/dev/null || true)

[ -z "${diff_output}" ] && exit 0

PYTHON3_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON3_BIN="python3"
else
  echo "any-usage-gate: WARNING: python3 が見つからないため typing.Any の直接 import 検出（複数行 import / alias 対応）を省略します。" >&2
fi

# 対象ファイルが HEAD 時点で `from typing import ...` により Any をどの
# ローカル名（alias 含む）に束縛しているかを AST で解決する。単一行の正規表現
# ではなく AST を使うのは、複数行の括弧 import
# (`from typing import (\n    Any,\n)`) を正しく扱うため。
_PYTHON_ANY_ALIAS_RESOLVER='
import ast
import sys

try:
    tree = ast.parse(sys.stdin.read())
except SyntaxError:
    sys.exit(0)

names = set()
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module == "typing":
        for alias in node.names:
            if alias.name == "Any":
                names.add(alias.asname or alias.name)

for name in sorted(names):
    print(name)
'

resolve_python_any_aliases() {
  local file="$1"
  [ -z "${PYTHON3_BIN}" ] && return 0
  # `-c` でプログラムを渡す（`- <<EOF` だと heredoc が stdin を占有し、
  # git show の内容を sys.stdin.read() に渡せなくなるため使わない）。
  git show "HEAD:${file}" 2>/dev/null | "${PYTHON3_BIN}" -c "${_PYTHON_ANY_ALIAS_RESOLVER}"
}

while IFS= read -r line; do
  case "${line}" in
    "+++ b/"*)
      current_file="${line#+++ b/}"
      current_line=0
      current_file_any_aliases=()
      case "${current_file}" in
        *.py)
          while IFS= read -r alias_name; do
            [ -n "${alias_name}" ] && current_file_any_aliases+=("${alias_name}")
          done < <(resolve_python_any_aliases "${current_file}")
          ;;
      esac
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
    *.py|*.ts|*.tsx)
      ;;
    *)
      if [ "${current_line}" -gt 0 ]; then
        current_line=$((current_line + 1))
      fi
      continue
      ;;
  esac

  added="${line#+}"
  is_violation=0
  if [[ "${added}" =~ ${python_any_pattern} ]]; then
    is_violation=1
  elif [[ "${current_file}" == *.py ]] && [ "${#current_file_any_aliases[@]}" -gt 0 ]; then
    for alias_name in "${current_file_any_aliases[@]}"; do
      bare_alias_pattern="(^|[^A-Za-z0-9_.])${alias_name}([^A-Za-z0-9_]|\$)"
      if [[ "${added}" =~ ${bare_alias_pattern} ]]; then
        is_violation=1
        break
      fi
    done
  fi
  if [ "${is_violation}" -eq 0 ] && [[ "${added}" =~ ${typescript_any_pattern} ]]; then
    is_violation=1
  fi
  if [ "${is_violation}" -eq 1 ]; then
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
