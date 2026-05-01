#!/usr/bin/env bash
# 死活監視: youtube-stream.service の状態を 4 通りに分類し、anomaly のみ通知する。
#
# 4-way 分類:
#   ok      : active+running           （配信中、Result は問わない）
#   idle    : activating+auto-restart+success （RuntimeMaxSec=11h 到達後の 1h 休止）
#   manual  : inactive+dead+success    （systemctl stop）
#   anomaly : 上記以外                 （kill -9 / failed / Result≠success など）
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

# source されたとき（bash 関数の単体テスト用）はここで終了する。
# BASH_SOURCE[0] と $0 が一致する場合のみ「直接実行」。
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0 2>/dev/null || true
fi

readonly UNIT="youtube-stream"

# systemctl show -p ActiveState -p SubState -p Result --value は 3 行を順番に返す
mapfile -t _values < <(systemctl show "$UNIT" -p ActiveState -p SubState -p Result --value)
active="${_values[0]}"
sub="${_values[1]}"
result="${_values[2]}"

status="$(classify_status "$active" "$sub" "$result")"

case "$status" in
  ok|idle|manual)
    # 通知しない（cron 出力もしない: 正常時は無音）
    exit 0
    ;;
  anomaly)
    msg="[youtube-stream] anomaly detected: ActiveState=${active} SubState=${sub} Result=${result}"
    logger -t youtube-stream-healthcheck -- "$msg" || true
    "$(dirname "$0")/notify.sh" "$msg"
    exit 0
    ;;
esac
