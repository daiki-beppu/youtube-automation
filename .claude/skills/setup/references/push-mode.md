# 設定 push モード（運用中チャンネルの設定同期）

実行前に **[save-push-troubleshooting.md](save-push-troubleshooting.md)** を Read する。ローカル `config/channel/meta.json` の `youtube_channel` と `config/localizations.json` を YouTube チャンネルに反映、もしくは YouTube 側から取り込む。

**前提**: OAuth 認証完了済み (`auth/token.json` が存在) かつ `config/channel/meta.json` の `channel.channel_id` が設定済みであること。

push 方向は次の読み取り専用確認を順に実行する。

```bash
uv run yt-channel-settings diff
uv run yt-channel-settings push
```

dry-run の差分、対象 part、`meta.json::channel.channel_id` を提示し、ユーザー承認後だけ実反映する。

```bash
uv run yt-channel-settings push --apply
```

apply 後は `uv run yt-channel-settings diff` で反映後確認する。ただし YouTube の `localizations` は `brandingSettings` より反映が遅く、数分の伝播遅延が生じることがある。直後の diff に localization の差分だけが残っても 1 回の確認で push 失敗と判定せず、数分待ってから再度 diff を実行する。伝播待ちの間は同じ変更を再 apply しない。

**逆方向（pull: YouTube → local）が必要な場合**:

```bash
uv run yt-channel-settings pull               # dry-run: 取り込み内容のプレビュー
uv run yt-channel-settings pull --apply       # 実反映: meta.json と localizations.json を書き換え
```

pull は YouTube 側の手動編集を取り込む場合だけ使い、`--apply` 後は `git diff` で確認する。API 契約として、`brandingSettings` / `localizations` / `status` は別々の `channels().update()` で送り、`branding_settings cannot be used with other parts` を避ける。空の `localizations` は `Required` 400 になる。`--no-localizations` は localization を対象外にする。認可には `youtube.force-ssl` が必要で、古い `auth/token.json` の scope 不足時は再認証する。

## 障害時ガイダンス

詳細は **[save-push-troubleshooting.md](save-push-troubleshooting.md)** を Read する。`/setup --tool` 未完了は setup 完了まで停止し、quota / rate、誤チャンネル、branding push 失敗は原因解消まで書き込みを再実行しない。
