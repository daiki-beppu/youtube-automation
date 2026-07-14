# Object Design Examples（参考資料）

`objects` を `config/skills/collection-ideate.yaml` で定義するときの参考例。
**これは例示のみ** — 実際のオブジェクトは各チャンネルのコンセプトに合わせて自由に設計する。

差別化軸を使う例は `ttp_mode: false` 専用。`ttp_mode: true` では
`differentiation_axes` を無視し、転写元の高再生コレクションまたは勝ちパターンに
基づいて `objects.swappable` の値を定義する。

## 例 1: bobble（jazzhop BGM + アライグマキャラ）

Single-Step モードで、ベース参照画像の「左キャンドル + 右カクテル」をコレクションごとに差し替える構成。
`config/skills/collection-ideate.yaml` での記述例:

```yaml
ttp_mode: false

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

```yaml
objects:
  swappable:
    - slot: foreground_item
      description_template: "{item_name}, {material} texture, {state}"
      story_template: "冒険者が {location} で手にした {item_name}"
    - slot: background_element
      description_template: "{environment_feature}"
  fixed:
    - character
    - campfire
```

## オブジェクト設計の原則

- **命名は短く詩的に**（"Inkwell", "Wanderer's Cup" 等）
- **ストーリーは「誰が・どこで・なぜ」**を 1 文で描写
- **ビジュアルは具体的に**（形状・色・質感の 3 要素を必ず指定）
- **差し替えスロットは 2-3 個に絞る**。`ttp_mode: false` では視覚的差別化の単位にし、
  `ttp_mode: true` では差別化軸を使わず転写元の高再生パターンから値を決める

## composition_lock (#489) — TTP 維持のための構図ロック

`ttp_mode: false` かつ `composition_lock: true`
（`config/skills/collection-ideate.yaml` のトップレベル、デフォルト `true`）が有効なとき、
`differentiation_axes`（location / time_of_day / weather / activity / mood）は
**企画コンセプトの内部メタデータ**として扱い、**サムネ構図には反映しない**。
差別化は `objects.swappable` の slot 値だけで取る。

`ttp_mode: true` では `composition_lock` の値にかかわらず、この節の差別化軸を使う
企画候補生成を適用せず、転写元の高再生コレクションまたは勝ちパターンに基づいて
企画を作る。後続 skill の生成方針は変更しない。

`objects.fixed` は TTP 構図そのもの — 全コレクション共通の「揺るがない要素」を書く。

### 例: DF365 (Mental Stamina Mode のような matte-black car + 飛行機 TTP)

```yaml
ttp_mode: false
composition_lock: true   # トップレベル

differentiation_axes:
  - location
  - time_of_day
  - weather

objects:
  swappable:
    - slot: car_model
      description_template: "matte-black {body_style} car"
      story_template: "{persona} が {scene} で乗る愛車"
    - slot: aircraft_silhouette
      description_template: "{aircraft_type} positioned at mid-distance background"
  fixed:
    - wet_runway
    - matte_black_car
    - aircraft_mid_distance
    - blue_hour
    - low_three_quarter_angle
```

このとき:

- 企画 A "mountain airstrip" / 企画 B "urban tunnel exit" / 企画 C "desert airstrip"
  と location 軸を変えても、**サムネ構図は wet_runway + blue_hour で固定** され、
  TTP 参照画像のスタイルアンカーが効き続ける。
- `differentiation_axes` の値は音楽プロンプト・概要欄・タイトルバリエーション
  （内部メタデータ）に反映される。
- `objects.swappable` の `car_model` / `aircraft_silhouette` を企画ごとに変えて
  視覚的差別化を取る（sedan / coupe / 戦闘機 / ビジネスジェット ...）。

`objects.fixed` のキーは `youtube_automation.utils.composition_lock.expand_fixed_objects()`
で TTP プロンプト定型節へ自動展開される。既知キー（`wet_runway`,
`matte_black_car`, `aircraft_mid_distance`, `blue_hour`, `low_three_quarter_angle`,
`rain_window`, `turntable`, `campfire`, `character` ...）はビルトイン辞書を持ち、
未知キーはキー名のアンダースコアをスペース化して passthrough する。

生成後セルフチェック（`yt-thumbnail-check`）も同じ `objects.fixed` を読んで
Gemini Vision に YES/NO 検査させる。詳細は `collection-ideate` SKILL.md の
「4-4-check: 生成後セルフチェック」節を参照。
