#!/usr/bin/env bash
# issue 粒度 lint（non-blocking）。
# GitHub issue イベントの JSON ペイロード（$GITHUB_EVENT_PATH 相当）を第 1 引数で受け取り、
# 粒度規約（`/issue` `/to-issues` スキルのスコープ上限ガード）に反するものを
# 警告メッセージとして stdout に出力する。警告が無ければ何も出力しない（exit 0）。
set -eu

payload="$1"

body=$(jq -r '.issue.body // ""' "$payload")
labels=$(jq -r '[.issue.labels[].name] | join(",")' "$payload")

# skip 条件: epic ラベル、または takt 実行対象ラベルが無い issue
case ",${labels}," in
  *,epic,*)
    exit 0
    ;;
esac

is_takt_target=0
case ",${labels}," in
  *,takt:default,*) is_takt_target=1 ;;
esac
case ",${labels}," in
  *,takt:default-mini,*) is_takt_target=1 ;;
esac
case ",${labels}," in
  *,takt:mini,*) is_takt_target=1 ;;
esac

if [ "$is_takt_target" -ne 1 ]; then
  exit 0
fi

warnings=""

add_warning() {
  warnings="${warnings}- ${1}
"
}

has_scope_out=$(printf '%s\n' "$body" | awk '/^## スコープ外/{print 1; exit} END{}')
if [ -z "$has_scope_out" ]; then
  add_warning '**`## スコープ外` セクションがありません**（省略不可。takt が隣接スライスの仕事を取り込むのを防ぐ境界です）'
fi

has_requirements=$(printf '%s\n' "$body" | awk '/^## 要件/{print 1; exit} END{}')
if [ -z "$has_requirements" ]; then
  add_warning '**`## 要件` セクションがありません**（番号付きリストで検証可能な完了条件を書いてください）'
fi

req_count=$(printf '%s\n' "$body" | awk '/^## 要件/{f=1;next} /^## /{f=0} f && /^[0-9]+\./{c++} END{print c+0}')
if [ "$req_count" -ge 8 ]; then
  add_warning "**要件が ${req_count} 件あります**（上限目安 7 件。sub-issue への分割を推奨）"
fi

if [ -n "$warnings" ]; then
  cat <<EOF
🔍 **issue 粒度 lint**（non-blocking — 参考情報です）

${warnings}
粒度規約: 1 issue = takt 1 run = 小さな PR 1 本。要件 7 件以下・影響ファイル 9 以下・機能領域 1 つ。詳細は \`/issue\`・\`/to-issues\` スキルのスコープ上限ガード参照。
EOF
fi
