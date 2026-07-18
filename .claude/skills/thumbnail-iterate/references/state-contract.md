# Thumbnail iterate state contract

すべて repository root 相対。writer は `thumbnail-iterate-state.py` だけとし、JSON は atomic replace する。

## Plan input

```json
{
  "video_id": "YouTube video ID",
  "collection": "collections/planning/example",
  "target_ctr": 6.0,
  "channel_average_ctr": 4.0,
  "browse_share": 35.0,
  "suggested_share": 25.0,
  "hypotheses": ["color", "composition"],
  "round_type": "controlled",
  "candidates": [
    {"id": "A", "file": "collections/planning/example/10-assets/thumbnail.jpg", "changed_elements": []},
    {"id": "B", "file": "collections/planning/example/10-assets/thumbnail-v2.jpg", "changed_elements": ["color"]},
    {"id": "C", "file": "collections/planning/example/10-assets/thumbnail-v3.jpg", "changed_elements": ["composition"]}
  ]
}
```

`hypotheses` は `composition` / `text` / `color` / `subject` / `expression` の 1〜2 個。通常比較は B/C ごとに 1 要素だけ変える。複数の独立 winner を統合する final round だけ `round_type: coherent_synthesis` とし、B/C は pending 要素を一貫した 1 枚として 2 個以上変えてよい。

## Outputs

- `data/thumbnail-iterate/runs/<video-id>.json`: 因果判定、候補 hash、状態。因果閾値未達も `stopped` として残す。
- `data/thumbnail-iterate/champion.json`: Studio 履歴と plan の file/hash が一致した winner のみ。winner は content hash 名で `champions/` に snapshot し、次回生成の immutable internal TTP にする。
- `data/thumbnail-iterate/synthesis-required.json`: 異なる要素が別 round で勝ったときの pending contract。現 champion は final round が勝つまで維持する。

## Exit codes

| code | meaning |
|---|---|
| 0 | plan 保存、winner/勝者なしの安全な反映 |
| 1 | JSON、パス、symlink、要素差分、hash、履歴対応の契約違反 |
| 2 | CTR または流入構成比が因果閾値未達。`/flop-analysis` へ route |
| 3 | 複数 winner 要素を coherent regeneration + final comparison すべき状態 |
