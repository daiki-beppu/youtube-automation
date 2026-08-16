# workflow state / tracking の Git 管理移行

ADR-0024 の制御面として、次の JSON をチャンネルリポジトリで Git 管理します。

- `collections/*/*/workflow-state.json`
- `collections/*/*/20-documentation/upload_tracking.json`
- `post_publish_history.json`
- `pinned_comment_history.json`

新規チャンネルは `yt-channel-init` と `yt-skills sync` が生成する `.gitignore` にこの規則を含みます。既存 `.gitignore` は `sync --force` でも上書きしません。

既存チャンネルでは対象 root を必ず明示し、最初に読み取り専用の差分を確認します。

```bash
uv run yt-skills migrate-state-git --channel-dir /absolute/path/to/channel --dry-run
uv run yt-skills migrate-state-git --channel-dir /absolute/path/to/channel
git diff --cached --check
git diff --cached
git commit -m "chore: workflow stateをGit管理へ移行する"
uv run yt-skills migrate-state-git --channel-dir /absolute/path/to/channel --check
```

移行コマンドはリポジトリ全域を再帰走査せず、指定した channel root の既知の配置だけを検査します。対象 JSON の symlink、壊れた JSON、secret 候補、移行対象外の staged / dirty / untracked 変更を検出した場合は `.gitignore` や Git index を変更せず停止します。`upload_tracking.json` に resumable upload session URI が残っている場合は、外部 write の再開状態を解消してから再実行してください。

`--check` はポリシーと対象 JSON が commit 済みで、未追跡・staged・dirty でないことを検査します。対象ファイルがまだ生成されていない新規チャンネルでは、ポリシーが commit 済みなら合格します。

実行時は `infrastructure.vcs.state_sync` が ADR-0024 の同期境界を所有します。reader は `pull_then_read()`、writer は `pull_update_commit_push()` を使い、後者には state owner の更新 callback と1行の commit messageを渡します。writer が変更できるのは既知の制御面 JSON だけです。開始時に worktree が clean でない場合、pull が fast-forward できない場合、または対象外ファイルが変更された場合は停止します。

push が non-fast-forward で拒否された場合は自動 merge / rebase / retryを行いません。`StateSyncEventKind.NON_FAST_FORWARD` を `on_event` callbackへ1回渡して `StateSyncError` で停止するため、呼び出し側はこのeventをDiscord等の通知adapterへ接続できます。event payloadはrepository pathと固定診断だけを持ち、remote URLや認証情報を含みません。競合解消は工程所有者が明示的に行ってください。
