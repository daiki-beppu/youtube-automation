# Analytics dashboard

`yt-dashboard` は登録済みチャンネルの収集済み Analytics snapshot を、ローカルブラウザで横断表示する読み取り専用 UI です。YouTube API への通信やデータ更新は行いません。

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

既定 URL は `http://127.0.0.1:8765/` です。別 port は `--port 9000`、別 registry は `--registry /absolute/path/channels.json` で指定できます。server は外部 interface へ bind せず、loopback だけで UI と JSON API を同一 origin 配信します。

## 表示内容

- チャンネルごとの最新 snapshot、収集日時、動画数、主要指標
- 選択チャンネルの再生数上位 chart と動画別 Table
- registry、meta、snapshot の欠損・破損状態

操作は pointer のほか、Tab でチャンネルへ移動し Enter / Space で詳細を開けます。配色は system theme に追従し、`d` キーで light / dark を切り替えられます。

frontend の開発・build・配布確認コマンドは [development.md](development.md#dashboard-開発) を参照してください。
