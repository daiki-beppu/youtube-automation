#!/bin/zsh
# PROTOTYPE #4896: 完了後 1 時間・2 時間・翌日に response_url / CDN URL の保持を確認する
cd "$(dirname "$0")/.."
PY=/Users/mba/ghq/github.com/daiki-beppu/youtube-automation/.venv/bin/python
for wait in 3600 3600 79200; do
  sleep $wait
  $PY fal_h3_compare.py recheck --out out >> out/recheck-schedule.log 2>&1
done
