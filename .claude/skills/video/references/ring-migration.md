# Ring visualizer の upstream 移行

旧 channel-local patch の ring は upstream の `overlays.audio_visualizer.style: ring` へ統合済みです。`yt-skills sync` 後に patch を再適用せず、`config/channel/youtube.json` のキーを次のように移行します。

| 旧 channel-local patch | upstream native |
|---|---|
| `ring.inner_radius` | `ring.inner_r` |
| `ring.thickness` | `ring.length` |
| `ring.diameter` | `2 * (inner_r + length)` から自動算出するため削除 |
| `ring.fill_image: conical-rainbow.png` | `fill.type: conical` |
| `ring.arc_deg` | `ring.arc_deg`（変更なし） |

移行例:

```json
{
  "overlays": {
    "enabled": true,
    "audio_visualizer": {
      "enabled": true,
      "style": "ring",
      "bars": 36,
      "ring": {
        "inner_r": 125,
        "length": 105,
        "arc_deg": [30, 330]
      },
      "fill": {
        "type": "conical"
      }
    }
  }
}
```

`conical` は実行時に ring の直径へ合わせた画像を生成し、色相を中心からの角度へ対応させます。外部 PNG と固定 `diameter` は不要です。
