# scheduled_publish_at フィールド追加

## Context

Analytics 収集で出力される `published_at` は YouTube API の値で、動画のアップロード時刻が入ることがある。
予約公開を使用している場合、実際の公開日時は `upload_tracking.json` の `publish_at` フィールドに記録されている。

この2つが区別できないため、分析時に「まだ公開されていない動画」を「公開済みで0再生」と誤認するケースが発生した。

`scheduled_publish_at` を analytics 出力に追加し、正確な投稿間隔分析・公開前動画の除外を可能にする。

## Design

### 変更対象

`/Users/mba/02-yt/automation/src/youtube_automation/utils/channel_analytics.py`
- `collect_basic_analytics()` メソッド内

### 実装方針

1. `video_data` dict 構築後（L106 付近）、`collections/live/` 配下の全 `upload_tracking.json` を走査
2. `video_id` をキーにして `publish_at` のマッピングを構築
3. 各 `video_data` エントリに `scheduled_publish_at` を注入

### 新規ヘルパー関数

`channel_analytics.py` に `_build_publish_at_map()` プライベートメソッドを追加:

```python
def _build_publish_at_map(self) -> dict[str, str]:
    """collections/live/ の upload_tracking.json から video_id → publish_at マップを構築。"""
    publish_map = {}
    channel_dir = ChannelConfig.channel_dir()
    live_dir = channel_dir / 'collections' / 'live'
    if not live_dir.exists():
        return publish_map
    for collection_dir in live_dir.iterdir():
        if not collection_dir.is_dir():
            continue
        tracking = collection_dir / '20-documentation' / 'upload_tracking.json'
        if not tracking.exists():
            continue
        try:
            data = json.loads(tracking.read_text())
            cc = data.get('complete_collection', {})
            vid = cc.get('video_id')
            pub = cc.get('publish_at')
            if vid and pub:
                publish_map[vid] = pub
        except (json.JSONDecodeError, OSError):
            continue
    return publish_map
```

### `collect_basic_analytics()` での注入

```python
# video_data dict 構築後に追加
publish_at_map = self._build_publish_at_map()
for vid, entry in video_data.items():
    entry['scheduled_publish_at'] = publish_at_map.get(vid)
```

### 出力スキーマ

```json
{
  "video_analytics": {
    "<video_id>": {
      "video_id": "RYBdUugsoSI",
      "published_at": "2026-03-26T02:00:18Z",
      "scheduled_publish_at": "2026-03-26T11:00:00+09:00",
      ...
    }
  }
}
```

- `scheduled_publish_at`: `upload_tracking.json` の `publish_at` 値（ISO 8601 + TZ）。マッチしない場合は `null`

### 依存関係

- `ChannelConfig` — 既にインポート済み（channel_dir 解決用）
- `json` — 標準ライブラリ
- `CollectionPaths` — パス定数のみ参照するため直接利用不要（ハードコードで十分）

### 変更しないもの

- `strategic_analysis` セクション — `video_analytics` に入れば十分
- `upload_tracking.json` のスキーマ — 読み取り専用
- 既存フィールド — 後方互換を維持

## Verification

1. `uv run yt-analytics` を実行
2. 出力 JSON の `video_analytics` 内の各エントリに `scheduled_publish_at` が存在することを確認
3. 予約公開済み動画: ISO 8601 + TZ 文字列
4. マッチしない動画: `null`
5. 既存フィールドが壊れていないことを確認
