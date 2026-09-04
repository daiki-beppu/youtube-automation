# `--thumbnail` の手順

collection 型ショートの素材として `10-assets/short.png`（9:16 縦型画像）と、必要に応じて `10-assets/short-loop.mp4`（Veo または fal.ai の 9:16 ループ動画）を準備する。

## 完了条件

- `10-assets/short.png` が生成され、画像チェックを満たしてユーザー承認済み
- ループ動画化する場合は `10-assets/short-loop.mp4` が生成され、ループ品質を確認済み

## Subagent Contract

- **入力**: 対象 collection、`10-assets/main.png/jpg`、生成対象、確定済み prompt
- **成果物**: `10-assets/short.png`、指定時は `10-assets/short-loop.mp4`
- **委譲しない処理**: 画像承認・Veo 課金・ループ品質確認。メインが承認を得てから該当処理を委譲する

subagent は `workflow-state.json` を更新せず、ユーザー確認を行わない。完了報告は `status: success | failure`、成果物の絶対パス一覧、エラーを返す。

## 前提

- `config/channel/` がロード可能（`load_config()`）。存在しない場合は `/setup --import` を案内して停止する
- `config.youtube.content_model.type == "collection"`。release 型では停止する
- Vertex AI ADC 初期化済み。未初期化なら `gcloud auth application-default login` と quota project 設定を案内する
- `10-assets/main.png` または `main.jpg` が存在する。無ければ `/thumbnail` で textless 背景を準備するよう案内する

## Step 1: 参考ビジュアルを確認する

```bash
open <collection-path>/10-assets/main.*
```

16:9 をクロップせず、シーンのキャラクター・背景・小道具・カラーを参考に 9:16 構図でゼロから再描写する。

## Step 2: プロンプトを作る

[prompt-template.md](prompt-template.md) に沿って次を含める。

1. 冒頭の `Tall vertical portrait composition.`
2. 9:16 の上下方向を活かしたシーン描写
3. タイトル / チャンネル名 / CTA のテキスト 3 層
4. template のスタイル句

キャラクターは中央〜やや下、斜め後ろまたは横顔を基本とし、上部にテキスト空間を確保する。

## Step 3: 9:16 画像を生成する

```bash
uv run yt-generate-image \
  --aspect-ratio "9:16" \
  --prompt "<Step 2 のプロンプト>" \
  --output <collection-path>/10-assets/short.png \
  -y
```

出力解像度は provider の `--size` 設定に従う。`--reference` は 16:9 構図へ引っ張られるため使わない。

## Step 4: 画像を確認・承認する

```bash
open <collection-path>/10-assets/short.png
```

再生成時は `short-v2.png` のように自動バージョニングする。

- [ ] 9:16 縦型
- [ ] テキスト 3 層が読める
- [ ] 斜め後ろ / 横顔構図でカメラ目線ではない
- [ ] main ビジュアルと世界観が一貫している
- [ ] 明るく鮮やかなカラー

## Step 5: ループ動画化する

承認された `short.png` を既定の Veo で変換する。MiniMax H3 を使う場合は fal engine を明示する。

```bash
uv run yt-generate-shorts-loop <collection-path> -y
```

fal.ai を使う場合（入力 768x1344、出力 1080x1920）:

```bash
uv run yt-generate-shorts-loop <collection-path> --engine fal -y
```

カスタム動作も指定できる。

```bash
uv run yt-generate-shorts-loop <collection-path> \
  --prompt "Gentle character animation: the woman slowly turns her head, hair sways in the breeze. Keep all text static and unchanged." \
  -y
```

出力は `10-assets/short-loop.mp4`（9:16、約 7 秒、末尾 1 秒自動トリム）。

```bash
open <collection-path>/10-assets/short-loop.mp4
```

- [ ] テキスト 3 層が崩れていない
- [ ] キャラクターが自然に動く
- [ ] ループの継ぎ目が自然

## 設定

| 配置 | 責務 |
|---|---|
| `.claude/skills/short/config.default.yaml` の `engine` / `veo` / `fal` | 既定 engine と engine 別モデル・生成設定。未定義時は CLI 内蔵値 |
| `config/skills/short.yaml` | `yt-generate-shorts-loop` の skill-config 上書き |
| `config/channel/meta.json` | channel name |
| `config/channel/audio.json` | CTA に使う target duration |

## Gotchas

- `--aspect-ratio "9:16"` を省略しない
- CTA の時間は `audio.target_duration_min / 60` から解決する
- prompt に `Keep all text completely static and unchanged` を含める
- Veo の末尾ノイズは canonical `generate_short_loop.py` が既定で 1 秒トリムする
- `short.jpg` は `short.png` 不在時の loop CLI 入力 fallback

## 所要時間と完了報告

画像生成は通常 10〜30 秒、ループ生成は 30〜90 秒。`/tmp/short-thumbnail-$(date +%s).log` へ redirect し、`short.png` / `short-loop.mp4` の絶対パスを報告する。

完了後は `/short <collection-path>` の通常手順へ戻る。
