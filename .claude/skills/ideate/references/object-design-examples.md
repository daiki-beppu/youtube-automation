# Object Design Examples（参考資料）

`objects` を `config/skills/ideate.yaml` で定義するときの参考例。
**これは例示のみ** — 実際のオブジェクトは各チャンネルのコンセプトに合わせて自由に設計する。

## 例 1: bobble（jazzhop BGM + アライグマキャラ）

Single-Step モードで、ベース参照画像の「左キャンドル + 右カクテル」をコレクションごとに差し替える構成。
`config/skills/ideate.yaml` での記述例:

```yaml
objects:
  swappable:
    - slot: left_candle
      description_template: "sage green glass jar with rich glossy candy-like translucent texture, evoking late-night studio warmth and dried paint"
      story_template: "{theme} に合わせて香りが変わる深夜のスタジオキャンドル"
    - slot: right_cocktail
      description_template: "an original cocktail called {name} — {color_description} in a {glass}, {flavor_note}"
      story_template: "ペルソナ {persona} が {scene} で飲む一杯"
  fixed:
    - turntable
    - rain_window

differentiation_axes:
  - location
  - time_of_day
  - activity
  - mood
```

コレクションごとに:
- `left_candle` の色 + 質感をテーマに合わせて変える（sage green / warm gold / pale amber ...）
- `right_cocktail` の名前 + 色 + グラス形状を変える（Inkwell / Aviation / Old Fashioned ...）
- `turntable`, `rain_window` は全コレクション共通

## 例 2: RPG / ファンタジー系チャンネル

装備品・道具・環境要素をオブジェクトスロットにする例。

```json
{
  "ideate": {
    "objects": {
      "swappable": [
        {
          "slot": "foreground_item",
          "description_template": "{item_name}, {material} texture, {state}",
          "story_template": "冒険者が {location} で手にした {item_name}"
        },
        {
          "slot": "background_element",
          "description_template": "{environment_feature}"
        }
      ],
      "fixed": ["character", "campfire"]
    }
  }
}
```

## オブジェクト設計の原則

- **命名は短く詩的に**（"Inkwell", "Wanderer's Cup" 等）
- **ストーリーは「誰が・どこで・なぜ」**を 1 文で描写
- **ビジュアルは具体的に**（形状・色・質感の 3 要素を必ず指定）
- **差し替えスロットは 2-3 個に絞る**（視覚的差別化のための単位）
