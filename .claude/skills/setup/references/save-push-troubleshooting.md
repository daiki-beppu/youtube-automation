# Settings push and troubleshooting details

設定 push モードと障害対応の実施詳細を定義する。mode routing、不可逆操作前の承認、実行コマンドと順序、完了・停止条件、成果物は `../SKILL.md` を正とする。新規開設 Step 10 の初回保存は `/setup --channel` の `setup/references/channel-mode.md` が所有する。

## Settings push details

設定 push はローカルの次の値を認証済み YouTube チャンネルへ同期する。

- `config/channel/meta.json::youtube_channel`: description / keywords / country / default language / unsubscribed trailer / made for kids
- `config/localizations.json`: 対応言語ごとの title / description

push 方向では root の順序どおり、読み取り専用 diff、push dry-run、ユーザー承認、`--apply` を実行する。dry-run は `channels().update()` を呼ばない。認証済みチャンネル ID と `meta.json::channel.channel_id` の一致を確認し、差分と対象 part をユーザーが承認するまで apply しない。

apply 後は `uv run yt-channel-settings diff` で反映を確認する。YouTube の `localizations` には数分の伝播遅延が生じることがあり、`brandingSettings` や default language だけが先に反映された部分失敗のような状態を一時的に返す。直後の diff に localization の差分だけが残る場合は失敗と断定せず、数分待ってから再度 diff を実行する。待機中は同じ変更を再 apply しない。再確認後も差分が残る場合に限り、通常の障害調査へ進む。

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
| localizations の反映待ち | apply は成功したが、直後の diff に localization の差分だけが残る | 数分の伝播遅延を見込み、同じ変更を再 apply しないで待ってから再度 diff を実行する。再確認後も差分が残る場合だけ障害として調査する。 |
| localizations の反映漏れ | 数分待って再確認しても localization の差分が残る | #562 の `ja`→`ja_JP` 正規化と `defaultLanguage` 一致条件による silent skip を疑い、通常の障害調査へ進む。 |
