# `/short --thumbnail` プロンプトテンプレート

`/short --thumbnail` の画像生成で使う 9:16 縦型プロンプトのテンプレートと例。

## 構造（4 ブロック）

```text
[縦型構図の指定]
[シーン・キャラクター描写（既存サムネを参考に、9:16 構図でゼロから再描写）]
[テキスト指示（3 層）]
[スタイル句]
```

## 1. 縦型構図の指定

```text
Tall vertical portrait composition.
```

冒頭に必ず置く。これがないと Gemini は 9:16 を活かさず横長前提の構図を返す。

## 2. シーン描写ガイド

- **環境ディテール**: 縦長を活かして天井・床・空・地面まで描写
- **キャラクター位置**: 画面中央〜やや下（上部にテキスト空間確保）
- **カメラアングル**: 斜め後ろ / 横顔推奨。有名キャラ（PD）は斜め前可、カメラ目線 NG

## 3. テキスト指示（3 層）

| 層 | 内容 | 位置 | フォントスタイル |
|---|---|---|---|
| タイトル | コレクション名 | 上部エリア | 大きめ、暖色アイボリー中世風 |
| チャンネル名 | `config/channel/meta.json` の `channel.name` | タイトル下 | やや小さめ、同スタイル |
| CTA | `Full {duration}-hour collection on channel` | 下部エリア | 小さめ、クリーン白 |

`{duration}` は `config/channel/audio.json` の `audio.target_duration_min` を 60 で割る。

テキスト装飾は控えめにし、`/thumbnail` の装飾ルールに準拠する。

## 4. スタイル句（末尾固定文）

```text
Hyper-detailed digital matte painting blending photorealism with subtle painterly
illustration touches, slightly stylized proportions and soft edges that hint at
hand-painted artwork, natural cinematic lighting with warm lens diffusion, rich
saturated colors pushed slightly beyond reality for emotional impact.
```

## 完成プロンプト例

```text
Tall vertical portrait composition. Inside a cozy medieval stone tower room,
a young woman with impossibly long golden hair sits on a wide stone windowsill
with her back to the viewer, painting on a canvas propped against the window
frame. She wears a blue peasant dress with paint stains. Her golden hair
cascades down and pools in flowing spirals across the wooden floor. Through
the tall arched window, a breathtaking sunset valley with waterfalls, a winding
river, distant castles and pine forests stretches below. Warm golden light
streams in. The room has stone walls, a wooden ceiling with string lights,
scattered art supplies, and stacked books. In the upper area, elegant white
fantasy text in stacked layout reads "Rapunzels Tower" in warm ivory
medieval-style font with subtle golden sparkle accents. Below that, smaller
text reads "Whispers Across the Hills" in matching style. Near the bottom,
gentle text reads "Full 2-hour collection on channel" in clean white font.
Hyper-detailed digital matte painting blending photorealism with subtle
painterly illustration touches, natural cinematic lighting with warm lens
diffusion, rich saturated colors.
```

## ループ動画の動作プロンプト

汎用形:

```text
Gentle character animation: the [subject] slowly [action], [hair/clothes/leaves]
sway in the breeze. Keep all text completely static and unchanged.
```

- 室内: `Gentle character animation: the woman slowly turns her head from the canvas to look out the window, golden hair sways in the breeze. Keep all text static.`
- 屋外: `Subtle environmental animation: leaves drift slowly in the foreground, light shafts shift gradually. Keep all text completely unchanged.`
- 水辺: `Calm water ripples gently, character's clothes flutter softly. Keep all text static and unchanged.`

`magical effects`、`particles`、`smoke`、`dramatic`、`falling leaves`、`butterflies` は原画にない要素や低品質な描画を誘発するため避ける。
