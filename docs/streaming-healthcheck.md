# streaming-healthcheck 運用手順書 (issue #109)

`youtube-stream.service` は **11 時間配信 → 1 時間休止 → 自動再開** のサイクルで自律的に回るため、素朴な「サービス active か」チェックでは 1 時間休止中（`activating (auto-restart)`）に毎回誤検知が出る（5 分間隔 × 1h = 12 回/サイクル）。本書は 4 シナリオの期待挙動と、誤発火・通知欠損が起きた場合の確認手順を示す。

## 状態分類（4-way）

`/opt/youtube-stream/bin/healthcheck.sh` は `systemctl show youtube-stream -p ActiveState,SubState,Result` の 3 値を以下のように分類する:

| systemd 状態 | 分類 | 通知 |
|---|---|---|
| `active+running` | `ok` | しない |
| `activating+auto-restart+success` | `idle` | しない |
| `inactive+dead+success` | `manual` | しない |
| その他（`Result≠success` 等） | `anomaly` | **送る** |

## 状態変化チェック（連打防止）

`healthcheck.sh` は cron が 5 分間隔で常時走るため、`anomaly` が続く間に毎回通知すると Discord が連打される（5/8 インシデント発覚）。これを抑止するため、前回の classify 結果を `/var/lib/youtube-stream/last_status` に保存し、**状態が変化したときだけ** 通知する:

| 前回 → 今回 | 通知 | メッセージ |
|---|---|---|
| `unknown` → `ok`/`idle`/`manual` | しない | （初回起動の通常確認） |
| `unknown` → `anomaly` | **送る** | `[youtube-stream] anomaly detected: ...` |
| `ok`/`idle`/`manual` → 同種類 or 別の正常系 | しない | （平常運用） |
| `ok`/`idle`/`manual` → `anomaly` | **送る** | `[youtube-stream] anomaly detected: ...` |
| `anomaly` → `anomaly` | しない | （連打防止） |
| `anomaly` → `ok`/`idle`/`manual` | **送る** | `[youtube-stream] recovered: <new>` |

`unknown` は `last_status` ファイル不在時のフォールバック値（VPS 再構築直後など）。初回 `ok` は無音、初回 `anomaly` は 1 通だけ通知が来る。

## テストシナリオ

### シナリオ 1: `pkill` による異常停止

```bash
ssh -i ~/.ssh/yt_stream_key root@<instance_ip>
# streaming 用 ffmpeg だけを狙い撃ち（コマンドラインに current.mp4 を含むプロセスに限定）
pkill -KILL -f 'ffmpeg .*current\.mp4'
```

`pgrep -f ffmpeg` で列挙 → `kill -9 <pid>` の手順は使わない。文字列 `ffmpeg` を含む別プロセス（手動デバッグ呼び出し等）を巻き込む可能性がある。

期待挙動:

- `systemctl show youtube-stream -p Result` が `core-dump` または `signal` を返す
- 5 分以内に `/etc/cron.d/youtube-stream-healthcheck` が `healthcheck.sh` を呼ぶ
- `classify_status` が `anomaly` を返し `notify.sh` が Discord に POST
- `journalctl -t youtube-stream-healthcheck` に `[youtube-stream] anomaly detected: ...` のログが残る

確認:

```bash
journalctl -t youtube-stream-healthcheck --since "5 minutes ago"
```

### シナリオ 2: 運用者による `systemctl stop`

```bash
systemctl stop youtube-stream
```

期待挙動:

- `ActiveState=inactive`, `SubState=dead`, `Result=success` になる
- `classify_status` が `manual` を返し **通知は飛ばない**（運用都合の停止と異常を切り分け）
- 復帰時は `systemctl start youtube-stream` を手動で実行する

確認:

```bash
# 5 分待ってから:
journalctl -t youtube-stream-healthcheck --since "10 minutes ago"
# anomaly のログが無いことを確認
```

### シナリオ 3: `RuntimeMaxSec=11h` 到達による正常停止

11 時間配信後、systemd が `RuntimeMaxSec` で SIGTERM を送り正常停止する。

期待挙動:

- 停止直後: `ActiveState=deactivating` または `inactive`, `Result=success`
- すぐに `Restart=always` + `RestartSec=1h` で `activating (auto-restart)` 状態へ遷移
- `classify_status` が `idle` を返し **通知は飛ばない**
- 5 分間隔の cron が 12 回走るが全て idle 判定で抑止される

確認:

```bash
# 11h 経過の境界で:
systemctl show youtube-stream -p ActiveState,SubState,Result
# → ActiveState=activating SubState=auto-restart Result=success が期待値
```

### シナリオ 4: 1 時間後の自動再開

`RestartSec=1h` 経過後、systemd が `youtube-stream.service` を自動再起動する。

期待挙動:

- 再起動成功で `ActiveState=active`, `SubState=running` に戻る
- `classify_status` は `ok` を返し通知は飛ばない（休止中の `idle` も合わせて 1 サイクル無音）
- ffmpeg が再度配信を始める（`journalctl -u youtube-stream -f` で確認）

## トラブルシューティング

### 誤発火（健全なのに通知が飛ぶ）

```bash
# 直近の状態履歴を確認
journalctl -u youtube-stream --since "1 hour ago"
# Result プロパティの遷移を確認（success 以外があれば原因）
systemctl show youtube-stream -p Result
```

### 通知が飛ばない（異常なのに無音）

```bash
# webhook URL が配置されているか
ls -l /etc/youtube-stream-healthcheck.env
# → -rw------- root:root

# notify.sh を直接呼んで Discord に届くか
/opt/youtube-stream/bin/notify.sh "manual test from VPS"

# cron が動いているか
systemctl status cron
grep CRON /var/log/syslog | tail
```

### `last_status` ファイルが破損 / 不整合

`/var/lib/youtube-stream/last_status` には `ok` / `idle` / `manual` / `anomaly` のいずれか 1 行が入る。手動編集や破損で値が壊れた場合は削除すれば次回 cron で再生成される（`unknown` フォールバックで動く）:

```bash
# 強制リセット（次回 cron で classify 結果が ok ならそのまま無音、anomaly なら 1 通通知）
rm -f /var/lib/youtube-stream/last_status
```

### ログが肥大化している

`/etc/logrotate.d/youtube-stream` で `daily / rotate 7 / copytruncate` のローテートが効いているはず。`copytruncate` は ffmpeg を再起動せずに inode を保ったまま truncate するため配信が止まらない。

```bash
logrotate -d /etc/logrotate.d/youtube-stream  # dry-run
```

## アーカイブ件数チェック（ローカル運用機側）

11h+1h サイクル × 1 日 2 サイクル → アーカイブ 2 本/日が期待値。下回ったら配信トラブルの可能性がある:

```bash
# 今日のアーカイブを確認
uv run yt-stream-archive-check --date "$(date -u +%F)" --notify-on-shortage

# 1 日 1 回の cron / launchd で実行する想定（OAuth token を VPS に置かないため）
```
