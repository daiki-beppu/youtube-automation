# Analytics dashboard

`yt-dashboard` は登録済みチャンネルの Analytics を起動時に更新し、ローカルブラウザで横断表示する読み取り中心の UI です。frontend は同一 origin の JSON API を読み取り、Python server が YouTube Data API と YouTube Analytics API を使用して各チャンネルの snapshot を保存します。

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

fresh な公開履歴 cache も再取得する場合は、強制更新を指定します。通常の Analytics 更新はそのまま行い、全登録チャンネルの公開履歴を再取得します。

```bash
uv run yt-dashboard --refresh-publications
```

OAuth を使わない配布確認やセルフ E2E で保存済み snapshot だけを表示する場合は、明示的に更新を止めます。

```bash
uv run yt-dashboard --skip-refresh
```

`--skip-refresh` と `--refresh-publications` を同時に指定した場合は `--skip-refresh` が優先され、公開履歴を含む API 更新は行いません。

既定 URL は `http://127.0.0.1:8765/` です。別 port は `--port 9000`、別 registry は `--registry /absolute/path/channels.json` で指定できます。server は外部 interface へ bind せず、loopback だけで UI と JSON API を同一 origin 配信します。

## JSON API

`GET /api/trends` は最新 snapshot の `channel_analytics.daily_metrics` と `reporting_api.impressions_summary.per_day` から、日次の再生数・再生時間・登録者純増減・インプレッション数を登録チャンネル順に返します。両データの日付和集合を使い、存在しない指標は `null` のまま保持します。snapshot が利用できないチャンネルは空の系列とエラー状態を返します。

`POST /api/refresh` は既存クライアント向けの互換入口です。全登録チャンネルを直列に再収集し、read model を再構築して更新後の overview を返します。JSON body の `days` は `7` / `30` / `90` を指定でき、省略時は `30` です。更新は排他的で、実行中の再送は `409 Conflict` です。`--skip-refresh` で起動した server では外部 API を呼ばず、保存済み snapshot から read model だけを再構築します。

`GET /api/publications` は、起動時に保存済み cache から構築した公開履歴 read model を読み取り専用で返します。同じ response の `days` に全チャンネルの日別合計、`channels` に登録順のチャンネル別内訳を含みます。各内訳は `status`、`fetched_at`、`timezone`、`days`、構造化された `error` を持ち、endpoint で公開日を再推測したり外部 API を呼んだりはしません。

`GET /api/pipeline` は登録チャンネルの `collections/{planning,live}/*/workflow-state.json` を canonical owner 経由で読み、phase、local / cloud の工程所有側、Suno 引き渡し状態、直近 state 更新時刻を返します。外部 API や R2 を照会せず、state が破損した collection は他のチャンネルを隠さず構造化エラーとして表示します。

## 表示内容

- チャンネルごとの最新 snapshot、収集日時、動画数、主要指標
- `status.publishAt` が現在より未来の YouTube 動画数（`公開予約 N本`）
- 選択チャンネルの再生数上位 chart と動画別 Table
- 全チャンネルの日次推移を再生数・再生時間・登録者純増減・インプレッション数で切り替える chart
- registry、meta、snapshot の欠損・破損状態と更新エラー
- 全チャンネルの collection phase、工程所有側、引き渡し状態、直近 state 更新

操作は pointer のほか、Tab でチャンネルへ移動し Enter / Space で詳細を開けます。配色は system theme に追従し、`d` キーで light / dark を切り替えられます。

frontend の開発・build・配布確認コマンドは [development.md](development.md#dashboard-開発) を参照してください。
