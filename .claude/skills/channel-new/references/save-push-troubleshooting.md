# Save, settings push, and troubleshooting details

新規開設モード Step 10 の初回保存、設定 push モード、障害対応の実施詳細を定義する。mode routing、不可逆操作前の承認、実行コマンドと順序、完了・停止条件、成果物は `../SKILL.md` を正とする。

## Initial save and cleanup details

`/channel-new` 完了直後は `/setup` と本スキルの生成物が未コミットで残りやすい。後続 `/automation-update` は dirty worktree で停止するため、最初と最後の `git status --porcelain` で cleanup 状態を判定する。

- 最初の出力が空なら、初回保存済みとして成功案内へ進む。
- 非空なら差分をユーザーへ提示し、root の順序どおり全変更を stage、一覧確認、secret guard、commit、最終確認する。
- ignore 済み `.env` は exclude pathspec 付き `git add` でも exit 1 になり得るため、`git add -A` 後の `initial_save_guard.sh` を唯一の安全境界とする。
- guard が失敗したら secret-like file は staged から自動で外れる。commit せず、`.gitignore` を確認してから再実行する。

remote 作成保留、git user identity 未設定、またはユーザーが今 commit しない判断をした場合は、次の案内を提示して保存未完了として停止する。

```text
未コミット変更が残っています。/automation-update の前に以下を完了してください:
  1. git status --short で差分を確認
  2. .env / auth/client_secrets.json / auth/token*.json が staged されていないことを確認
  3. git commit -m "chore: 初回チャンネル設定を保存"
```

作業ツリーが最初から clean、または初回 commit 後の `git status --porcelain` が空の場合だけ、root の成功案内を提示する。

## Settings push details

設定 push はローカルの次の値を認証済み YouTube チャンネルへ同期する。

- `config/channel/meta.json::youtube_channel`: description / keywords / country / default language / unsubscribed trailer / made for kids
- `config/localizations.json`: 対応言語ごとの title / description

push 方向では root の順序どおり、読み取り専用 diff、push dry-run、ユーザー承認、`--apply` を実行する。dry-run は `channels().update()` を呼ばない。認証済みチャンネル ID と `meta.json::channel.channel_id` の一致を確認し、差分と対象 part をユーザーが承認するまで apply しない。

YouTube 側の手動編集を local へ取り込む場合だけ pull を使う。pull dry-run で変更を確認し、承認後に `pull --apply` で `meta.json` と `config/localizations.json` を更新する。apply 後は `git diff` で保存内容を確認する。

## Settings API constraints

- apply は `brandingSettings` / `localizations` / `status` を別々の `channels().update()` として送る。`brandingSettings` と他 part の同時送信は `branding_settings cannot be used with other parts` の 400 になる。
- localizations を完全に空で送ると `Required` 400 になる。全ローカライゼーションを削除する場合も default language の 1 件を残し、送信しなかったロケールを YouTube 側で削除させる。
- `--no-localizations` は localizations の比較と送信をスキップし、branding と status だけを対象にする。
- apply には `youtube.force-ssl` scope が必要。古い `auth/token.json` で scope が不足する場合は token を削除して再認証する。

## Troubleshooting details

| 状況 | 兆候 | 対処 |
|---|---|---|
| `/setup` 未完了 | `auth/token.json` 不在、ADC 未設定、API 403 | `/setup` を完了するまで停止する。 |
| `gh` CLI 不在 / 未認証 | `command not found: gh`、`gh auth` エラー | `gh` を install して `gh auth login` を実行する。remote 作成だけ保留し、config 生成は継続できる。 |
| YouTube quota / rate | HTTP 429、403 `quotaExceeded` | 日次 quota リセットを待つか対象チャンネル数を絞る。書き込みへ進まない。 |
| seed が誤チャンネル | seed preview が想定と異なる | ユーザー確認で不採用にし、承認後コマンドを実行しない。 |
| branding push 失敗 | push apply が 400 / 403 | dry-run 差分、OAuth scope、`meta.json::channel.channel_id` を確認し、原因解消まで再 apply しない。 |
