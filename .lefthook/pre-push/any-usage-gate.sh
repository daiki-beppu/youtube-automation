#!/usr/bin/env bash
#
# 新規追加行の広すぎる Any / any 型注釈を検出する。
#
# 判定基準: origin/main からの分岐点（merge-base）と現在の HEAD の差分。
# diff の基準点（PRE_PUSH_DIFF_BASE）は changelog-gate.sh から呼ばれた場合は
# そちらで解決済みの値を再利用し、単体実行時のみ自前で解決する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -n "${PRE_PUSH_DIFF_BASE:-}" ]; then
  diff_base="${PRE_PUSH_DIFF_BASE}"
else
  BASE_REF="origin/main"
  if ! git rev-parse --verify --quiet "${BASE_REF}^{commit}" >/dev/null; then
    echo "any-usage-gate: ${BASE_REF} が無いためスキップします（CI / review で確認してください）。" >&2
    exit 0
  fi
  if ! diff_base=$(git merge-base "${BASE_REF}" HEAD 2>/dev/null); then
    diff_base="${BASE_REF}"
  fi
fi

current_file=""
current_line=0
# 現在のファイルで Any が実際に参照されている（コメント・文字列を除く）行番号の集合。
# " 3 7 12 " のようにスペース区切りで保持し、ケース文で部分一致検索する。
current_file_any_lines=" "
violations=()
# TypeScript の any は型位置（: any, ジェネリック引数 <any>, union/intersection,
# tuple 要素, 型エイリアス代入 = any, 型アサーション as any）に限定して検出する。
# 素の単語境界だけだと "any" を含む英語のコメントや文字列を誤検知するため、
# 型を導入する記号（: < , | & ( [ =）の直後、または `as` キーワードの後という
# 条件を必須にする。文字列・コメント自体の誤検知は後段の clean_ts_line で除去する。
typescript_any_pattern='(:|<|,|\||&|\(|\[|=)[[:space:]]*any([^A-Za-z0-9_$]|$)|(^|[^A-Za-z0-9_$])as[[:space:]]+any([^A-Za-z0-9_$]|$)'
diff_output=$(git diff --unified=0 --no-color "${diff_base}" HEAD -- 2>/dev/null || true)

[ -z "${diff_output}" ] && exit 0

PYTHON3_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON3_BIN="python3"
else
  echo "any-usage-gate: WARNING: python3 が見つからないため Python 側の Any 検出（typing.Any 修飾形・直接 import 経由の裸の Any）を省略します。" >&2
fi

# 対象ファイルが HEAD 時点でどの行に「実際に参照される」Any を持つかを AST で
# 解決する（.lefthook/pre-push/any_usage_python_resolver.py）。テキスト正規表現
# ではなく AST を使うのは、コメント・docstring・文字列リテラル中の "Any"
# （型使用ではない）を構造的に除外するため。
resolve_python_any_usage_lines() {
  local file="$1"
  [ -z "${PYTHON3_BIN}" ] && return 0
  git show "HEAD:${file}" 2>/dev/null | "${PYTHON3_BIN}" "${SCRIPT_DIR}/any_usage_python_resolver.py"
}

# TypeScript の追加行からコメント（// ...）と文字列・テンプレートリテラルの
# 中身を取り除いたものを返す（.lefthook/pre-push/any_usage_ts_line_cleaner.py）。
# コメント・文字列内の "any" を型使用として誤検知しないための事前クリーニング
# （正規表現マッチが疑わしい場合のみ呼ぶ）。
clean_ts_line() {
  local text="$1"
  [ -z "${PYTHON3_BIN}" ] && { printf '%s' "${text}"; return 0; }
  printf '%s' "${text}" | "${PYTHON3_BIN}" "${SCRIPT_DIR}/any_usage_ts_line_cleaner.py"
}

while IFS= read -r line; do
  case "${line}" in
    "+++ b/"*)
      current_file="${line#+++ b/}"
      current_line=0
      current_file_any_lines=" "
      case "${current_file}" in
        *.py)
          while IFS= read -r usage_line; do
            [ -n "${usage_line}" ] && current_file_any_lines="${current_file_any_lines}${usage_line} "
          done < <(resolve_python_any_usage_lines "${current_file}")
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
  case "${current_file}" in
    *.py)
      case "${current_file_any_lines}" in
        *" ${current_line} "*)
          is_violation=1
          ;;
      esac
      ;;
    *.ts|*.tsx)
      if [[ "${added}" =~ ${typescript_any_pattern} ]]; then
        # コメント・文字列内の any / typing.Any 的な言及を除外するため、
        # クリーニング後に再判定してから確定する。
        cleaned_added=$(clean_ts_line "${added}")
        if [[ "${cleaned_added}" =~ ${typescript_any_pattern} ]]; then
          is_violation=1
        fi
      fi
      ;;
  esac
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
