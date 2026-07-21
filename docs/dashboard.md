# Analytics dashboard

`yt-dashboard` は登録済みチャンネルの Analytics を起動時に更新し、ローカルブラウザで横断表示する UI です。frontend 自体は同一 origin の JSON API を読むだけですが、Python の起動処理は YouTube Data API と YouTube Analytics API を使用して各チャンネルの snapshot を保存します。

## channel registry

既定では `~/.config/tayk/channels.json` を読みます。各要素はチャンネル repository の絶対 path です。配列の順序が UI の表示順になります。

```json
[
  "/Users/example/channels/night-drive",
  "/Users/example/channels/coffee-jazz"
]
```

## 起動

```bash
uv run yt-dashboard --open
```

registry の全チャンネルを登録順に更新してから server を開始します。1 チャンネルが失敗しても残りを続行し、失敗したカードには前回 snapshot と更新エラーを表示します。API quota は概ねチャンネルごとの `yt-analytics` standard 収集に相当し、公開予約数の取得に動画 50 本ごとに `videos.list` 1 call が加わります。

OAuth を使わない配布確認やセルフ E2E で保存済み snapshot だけを表示する場合は、明示的に更新を止めます。

```bash
uv run yt-dashboard --skip-refresh
```

既定 URL は `http://127.0.0.1:8765/` です。別 port は `--port 9000`、別 registry は `--registry /absolute/path/channels.json` で指定できます。server は外部 interface へ bind せず、loopback だけで UI と JSON API を同一 origin 配信します。

## 表示内容

- チャンネルごとの最新 snapshot、収集日時、動画数、主要指標
- `status.publishAt` が現在より未来の YouTube 動画数（`公開予約 N本`）
- 選択チャンネルの再生数上位 chart と動画別 Table
- registry、meta、snapshot の欠損・破損状態と起動時更新エラー

操作は pointer のほか、Tab でチャンネルへ移動し Enter / Space で詳細を開けます。配色は system theme に追従し、`d` キーで light / dark を切り替えられます。

frontend の開発・build・配布確認コマンドは [development.md](development.md#dashboard-開発) を参照してください。
