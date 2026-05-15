#!/usr/bin/env bash
# youtube-stream.service の ExecStart から呼ばれる ffmpeg 起動ラッパー。
#
# 役割:
#   systemd が `EnvironmentFile=/etc/youtube-stream.env` で注入する
#   $VIDEO / $RTMP_URL をそのまま受け取り、ffmpeg を exec でプロセス置換する。
#   これにより systemd unit の ExecStart 行に $RTMP_URL が残らず、
#   `systemctl show youtube-stream` / `/proc/<pid>/cmdline` の unit レベル経路
#   から stream_key を含む RTMP URL が漏れない（issue #160）。
#
# env file を `source` しない理由:
#   `/etc/youtube-stream.env` は `chmod 600 root:root`（main.tf）で配置されて
#   おり、unit 側の `DynamicUser=yes`（#159）で起動されるラッパーは読み取れない。
#   systemd 自身が PID 1（root）で `EnvironmentFile=` を読み込み env を子プロセスへ
#   注入するため、ラッパー側で改めて `source` する必要はなく、行えば即 fail する。
#
# 注意:
#   `exec` でなく直接 `ffmpeg ...` を呼ぶと shell が親プロセスとして残り、
#   systemd の Restart / RuntimeMaxSec シグナルが ffmpeg に直接届かない。
#   ffmpeg 引数は youtube-stream.service.tftpl から一字一句移植（#185 の
#   `-c:v copy -c:a copy` 明示分離を維持）。

set -eu

exec /usr/bin/ffmpeg -re -stream_loop -1 -i "$VIDEO" -c:v copy -c:a copy -f flv "$RTMP_URL"
