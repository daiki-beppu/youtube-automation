#!/usr/bin/env bash
#
# CHANGELOG ゲート + pre-push 全ゲートの唯一のエントリポイント
#（lefthook pre-push から実行される）
#
# CI（.github/workflows/ci.yml の `changelog` ジョブ）と同じ判定をローカル再現し、
# 実コードを変更したのに CHANGELOG.md を更新していない push を止める。
#
# 判定基準: origin/main からの分岐点（merge-base）と現在の HEAD の差分。
#
# ゲート対象パス（いずれかが変更されたら CHANGELOG.md 更新が必須）:
#   - src/youtube_automation/
#   - .claude/skills/
#   - .claude/CLAUDE.template.md
#   - pyproject.toml
#   - packages/
#   - package.json
#
# tests/ や docs/ など上記以外のみの変更はゲート対象外（CI も自動 skip）。
#
# 意図的に省く: SKIP_CHANGELOG=1 git push（CHANGELOG チェックのみ省く。
# test-diff-gate / any-usage-gate は引き続き実行される）
#
# lefthook は同一 hook 内で use_stdin を持てるコマンドを 1 つに制限するため、
# ブランチ削除 push の判定はこのスクリプトが stdin から一度だけ読み取り、
# test-diff-gate.sh / any-usage-gate.sh を末尾で呼び出すことで同じ判定を共有する
# （削除 push はこの 3 ゲートすべてを対象外にする）。diff の基準点（merge-base）も
# ここで一度だけ解決し PRE_PUSH_DIFF_BASE として子ゲートへ export することで、
# 3 スクリプトが個別に origin/main / merge-base を再計算する重複を避ける。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# pre-push は stdin から "<local ref> <local sha> <remote ref> <remote sha>" を
# ref ごとに 1 行受け取る（lefthook.yml 側で use_stdin: true が必要）。
# local sha が全ゼロの行はブランチ削除 push（git push origin :branch）で、
# push されるコミットが存在しないため全ゲート対象外。
# 削除以外の ref が 1 つでもあれば従来通り HEAD 基準で判定する。
# stdin が空（手動実行など）の場合も従来通り判定にフォールバックする。
ZERO_SHA="0000000000000000000000000000000000000000"
if [ ! -t 0 ]; then
  ref_lines=0
  non_delete_refs=0
  # `|| [ -n ... ]` は末尾改行が無い最終行の取りこぼし防止（read が非ゼロを
  # 返しても変数が埋まっていれば 1 回だけ本体を実行する）
  while read -r _local_ref local_sha _remote_ref _remote_sha || [ -n "${local_sha:-}" ]; do
    [ -z "${local_sha:-}" ] && continue
    ref_lines=$((ref_lines + 1))
    if [ "${local_sha}" != "${ZERO_SHA}" ]; then
      non_delete_refs=$((non_delete_refs + 1))
    fi
  done
  if [ "${ref_lines}" -gt 0 ] && [ "${non_delete_refs}" -eq 0 ]; then
    echo "changelog-gate: ブランチ削除 push のためスキップします。" >&2
    exit 0
  fi
fi

# origin/main からの分岐点を全ゲート共通の基準点として一度だけ解決する。
BASE_REF="origin/main"
diff_base=""
if git rev-parse --verify --quiet "${BASE_REF}^{commit}" >/dev/null; then
  if ! diff_base=$(git merge-base "${BASE_REF}" HEAD 2>/dev/null); then
    diff_base="${BASE_REF}"
  fi
fi
export PRE_PUSH_DIFF_BASE="${diff_base}"

exit_code=0

if [ "${SKIP_CHANGELOG:-}" = "1" ]; then
  echo "changelog-gate: SKIP_CHANGELOG=1 のためスキップします。" >&2
else
  if [ -z "${diff_base}" ]; then
    echo "changelog-gate: ${BASE_REF} が無いためスキップします（CI で判定されます）。" >&2
  else
    changed_files=$(git diff --name-only "${diff_base}" HEAD 2>/dev/null || true)

    if [ -n "${changed_files}" ]; then
      GATED_PATHS=(
        "src/youtube_automation/"
        ".claude/skills/"
        ".claude/CLAUDE.template.md"
        "pyproject.toml"
        "packages/"
        "package.json"
      )
      CHANGELOG_PATH="CHANGELOG.md"

      code_touched=0
      while IFS= read -r f; do
        [ -z "$f" ] && continue
        for p in "${GATED_PATHS[@]}"; do
          case "$f" in
            "$p"*)
              code_touched=1
              break
              ;;
          esac
        done
        [ "$code_touched" = "1" ] && break
      done <<EOF
${changed_files}
EOF

      if [ "${code_touched}" = "1" ]; then
        changelog_touched=0
        while IFS= read -r f; do
          if [ "$f" = "${CHANGELOG_PATH}" ]; then
            changelog_touched=1
            break
          fi
        done <<EOF
${changed_files}
EOF

        if [ "${changelog_touched}" = "0" ]; then
          echo "" >&2
          echo "changelog-gate: ❌ CHANGELOG ゲート違反" >&2
          echo "  実コード（src/youtube_automation/ / .claude/skills/ / .claude/CLAUDE.template.md / pyproject.toml / packages/ / package.json）を" >&2
          echo "  変更していますが ${CHANGELOG_PATH} が更新されていません。" >&2
          echo "  基準: ${diff_base}" >&2
          echo "" >&2
          echo "  対処:" >&2
          echo "    - ${CHANGELOG_PATH} の [Unreleased] に変更点を追記する" >&2
          echo "    - もしくは CHANGELOG 不要な変更なら: SKIP_CHANGELOG=1 git push" >&2
          echo "" >&2
          exit_code=1
        fi
      fi
    fi
  fi
fi

if ! bash "${SCRIPT_DIR}/test-diff-gate.sh"; then
  exit_code=1
fi

if ! bash "${SCRIPT_DIR}/any-usage-gate.sh"; then
  exit_code=1
fi

exit "${exit_code}"
