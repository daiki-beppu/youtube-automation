# 予約投稿（スケジュール公開）セットアップ

YouTube Data API の `status.publishAt` を使った予約公開の正しい設定手順とトラブルシュート（#647 ユーザー FB 対応）。

## 仕組み

`CollectionUploader._calculate_publish_at()` が `config/schedule_config.json` の `schedule` セクションを読み、予約日時を計算する。計算結果は最終的にアップローダーへ渡り:

- `status.privacyStatus = "private"` を強制
- `status.publishAt = "<UTC ISO 8601>"` を設定

これにより YouTube 上で **「予約済み（scheduled）」状態** になる。`status.publishAt` を設定するには `privacyStatus=private` が必須（API 仕様）。

## 予約公開の有効化

`schedule_config.json` の `schedule` セクションに以下のいずれかを設定する:

### 方法 1: 明示的に有効化（推奨）

```json
{
  "schedule": {
    "timezone": "Asia/Tokyo",
    "auto_schedule_enabled": true,
    "publish_time": "20:00",
    "cadence": ["tue", "thu", "sat"]
  }
}
```

- `auto_schedule_enabled: true` を必ず明記
- `publish_time` で公開時刻（チャンネル TZ）
- `cadence` で公開曜日（省略時は全曜日許可）

### 方法 2: 暗黙オプトイン（#647）

ユーザーが `cadence` か `publish_time` を **明示設定** していれば、`auto_schedule_enabled` を省略しても予約公開が有効になる:

```json
{
  "schedule": {
    "timezone": "Asia/Tokyo",
    "publish_time": "20:00",
    "cadence": ["mon", "wed", "fri"]
  }
}
```

これは「予約投稿の設定をしたつもりが `auto_schedule_enabled` を入れ忘れて即時公開された」FB を踏まえた救済挙動（#647）。

### 即時公開を強制

`auto_schedule_enabled: false` を **明示** すれば、他のキーが設定されていても即時公開する:

```json
{
  "schedule": {
    "auto_schedule_enabled": false,
    "publish_time": "20:00",
    "cadence": ["tue", "thu"]
  }
}
```

## 検証手順

### 1. ドライランで確認（API 非消費）

```bash
bunx tayk upload-collection --plan -c <COLLECTION_NAME>
```

- 予約公開時 → `📅 公開予定: 2026-06-15T20:00:00+09:00`
- 即時公開時 → `📅 公開設定: 即時公開 (public)`
- 「設定したのに即時公開」の場合は `⚠️  schedule.auto_schedule_enabled が false ...` という警告が出る

### 2. 実アップロード後の YouTube 側状態確認

YouTube Studio または Data API で:

- `status.privacyStatus == "private"`
- `status.publishAt` に予約日時（UTC, Z 終端）が入る

```bash
# Data API で動画ステータスを確認する例
gcloud auth application-default login  # 初回のみ
curl -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://www.googleapis.com/youtube/v3/videos?part=status&id=<VIDEO_ID>"
```

期待値:

```json
{
  "items": [{
    "status": {
      "privacyStatus": "private",
      "publishAt": "2026-06-15T11:00:00.000Z",
      "uploadStatus": "processed"
    }
  }]
}
```

## トラブルシュート

### Q. 予約日時を指定したのに即時公開された

1. `--plan` で `schedule_config.json` の有効性を確認
2. `auto_schedule_enabled: false` が明示されていないか確認（明示 false は即時を強制する）
3. `config/channel/youtube.json` の `privacy_status` が `"public"` の場合、`publish_at` が `None` だと公開されるので、上記設定で予約日時が計算されているか改めて `--plan` で確認

### Q. publish_time の TZ がズレる

- `schedule.timezone`（例: `Asia/Tokyo`）を必ず設定する
- `_calculate_publish_at()` は `schedule.timezone` を使って HH:MM を解釈する
- アップローダーは内部で UTC へ正規化（`+09:00` → `Z`）して `status.publishAt` に渡すので、API 側でも常に同じ瞬間になる

### Q. cadence で土曜にしているのに金曜になった

- 既に公開済み / 予約済みの動画と同日に被ると、次の cadence 曜日にスライドする仕様
- ログに `📅 公開日スライド → ...` が出ているか確認

## 関連

- `agents/collection_uploader.py::_calculate_publish_at` — スケジュール計算ロジック
- `agents/collection_uploader.py::_scheduling_enabled` — 有効性判定ヘルパー（#647）
- `agents/youtube_auto_uploader.py::_normalize_publish_at` — `status.publishAt` の UTC 正規化
- YouTube Data API: <https://developers.google.com/youtube/v3/docs/videos>
