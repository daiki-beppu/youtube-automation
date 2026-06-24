#!/usr/bin/env bash
# 死活監視: youtube-stream.service の状態を 4 通りに分類し、anomaly のみ通知する。
#
# 4-way 分類:
#   ok      : active+running           （配信中、Result は問わない）
#   idle    : activating+auto-restart+success （stream_hours > 0 の RuntimeMaxSec 到達後の計画休止）
#   manual  : inactive+dead+success    （systemctl stop）
#   anomaly : 上記以外                 （kill -9 / failed / Result≠success など）
#
# break_hours=0 の RestartSec=10s はクラッシュ時の短い再起動間隔。failed / Result≠success は anomaly。
#
# 状態変化チェック（連打防止）: 前回 classify 結果を $STATE_DIR/last_status に保存し、
# anomaly 突入時と anomaly からの復帰時のみ通知する。同種類の連続は無音。
#
# cron は最小 PATH（/usr/bin:/bin）で実行されるため、systemctl 等が見つかるよう PATH を明示宣言する。

set -euo pipefail

# cron は最小 PATH（/usr/bin:/bin）で実行される。systemctl は通常 /usr/bin か /sbin
# にあるため、cron セーフなパスを末尾に append しておく（既存 PATH が空でも動く）。
export PATH="${PATH:+${PATH}:}/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# systemctl show の 3 値を ok / idle / manual / anomaly のいずれかに分類する純関数。
# stdout に分類名を 1 行 echo するだけ。
classify_status() {
  local active="$1"
  local sub="$2"
  local result="$3"

  if [[ "$active" == "active" && "$sub" == "running" ]]; then
    echo "ok"
    return
  fi

  if [[ "$active" == "activating" && "$sub" == "auto-restart" && "$result" == "success" ]]; then
    echo "idle"
    return
  fi

  if [[ "$active" == "inactive" && "$sub" == "dead" && "$result" == "success" ]]; then
    echo "manual"
    return
  fi

  # Fail Safe: 想定外の状態は通知側に倒す
  echo "anomaly"
}

# stdin の `KEY=VALUE` 行（systemctl show -p ... 出力）を読み、
# ActiveState/SubState/Result を呼び出し元 scope の active/sub/result 変数にセットする。
# `systemctl show ... --value` は property 引数順序を保証しないため `KEY=VALUE` 形式で
# パースする（順序非依存）。process substitution `< <(...)` で呼ぶ前提。
parse_systemctl_kv() {
  active=""
  sub=""
  result=""
  local line
  while IFS= read -r line; do
    case "$line" in
      ActiveState=*) active="${line#*=}" ;;
      SubState=*)    sub="${line#*=}" ;;
      Result=*)      result="${line#*=}" ;;
    esac
  done
}

# 前回 classify 結果と今回 classify 結果から通知アクションを決める純関数。
# 戻り値（stdout に 1 行 echo）:
#   ""         : 通知しない
#   "anomaly"  : anomaly 突入（[youtube-stream] anomaly detected: ...）
#   "recovered": anomaly からの復帰（[youtube-stream] recovered: <new>）
#
# 遷移表:
#   prev\current | ok/idle/manual | anomaly
#   -------------|----------------|--------
#   unknown      | ""             | anomaly   (初回は ok/idle/manual を無音、anomaly のみ通知)
#   ok/idle/manual | ""           | anomaly
#   anomaly      | recovered      | ""        (連打防止)
decide_notification() {
  local prev="$1"
  local current="$2"

  if [[ "$current" == "anomaly" ]]; then
    if [[ "$prev" == "anomaly" ]]; then
      echo ""
    else
      echo "anomaly"
    fi
    return
  fi

  # current is ok/idle/manual
  if [[ "$prev" == "anomaly" ]]; then
    echo "recovered"
  else
    echo ""
  fi
}

# source されたとき（bash 関数の単体テスト用）はここで終了する。
# BASH_SOURCE[0] と $0 が一致する場合のみ「直接実行」。
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

readonly UNIT="youtube-stream"
# STATE_DIR は本番では /var/lib/youtube-stream 固定。テスト時のみ YT_STREAM_STATE_DIR で override。
readonly STATE_DIR="${YT_STREAM_STATE_DIR:-/var/lib/youtube-stream}"
readonly LAST_STATUS_FILE="${STATE_DIR}/last_status"

mkdir -p "$STATE_DIR"

# 順序非依存パース（KEY=VALUE 形式）。process substitution で親 scope に変数を反映させる。
parse_systemctl_kv < <(systemctl show "$UNIT" -p ActiveState -p SubState -p Result)

status="$(classify_status "$active" "$sub" "$result")"

# 初回・破損時は unknown フォールバック（decide_notification の遷移表に従う）
prev="$(cat "$LAST_STATUS_FILE" 2>/dev/null || echo unknown)"
action="$(decide_notification "$prev" "$status")"

case "$action" in
  anomaly)
    msg="[youtube-stream] anomaly detected: ActiveState=${active} SubState=${sub} Result=${result}"
    logger -t youtube-stream-healthcheck -- "$msg" || true
    "$(dirname "$0")/notify.sh" "$msg"
    ;;
  recovered)
    msg="[youtube-stream] recovered: ${status}"
    logger -t youtube-stream-healthcheck -- "$msg" || true
    "$(dirname "$0")/notify.sh" "$msg"
    ;;
esac

# 通知有無に関わらず毎回保存（次回 cron の prev として使う）
printf '%s\n' "$status" > "$LAST_STATUS_FILE"
