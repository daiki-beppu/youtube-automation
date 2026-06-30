---
name: short-thumbnail
description: "Use when ショート動画用の 9:16 縦型サムネイル画像を作りたいとき。または承認済み `short.png` を Veo 3.1 で 9:16 ループ動画に変換したいとき。Gemini で縦型構図を生成し、必要に応じてキャラクターアニメ付きループ動画化。「ショートサムネ」「縦型サムネイル」「short.png」「short-loop」「9:16 画像」「9:16 ループ」など、ショート用ビジュアル制作の場面で必ず使用すること"
---

## Overview

`/short` Mode A の素材として `10-assets/short.png`（9:16 縦型サムネ）と
`10-assets/short-loop.mp4`（Veo 3.1 で生成した 9:16 ループ動画）を準備するための前段スキル。

## 前提

- `config/channel/` がロード可能（`load_config()`）
- Vertex AI ADC 初期化済み (`gcloud auth application-default login` + `set-quota-project`)。project_id は ADC quota project から自動解決（`GOOGLE_CLOUD_PROJECT` は任意で上書き可）
- `10-assets/main.png` または `main.jpg`（16:9 textless 動画背景 / 参考ビジュアル）が既存

## Quick Reference

| コマンド | 説明 |
|---------|------|
| `uv run yt-generate-image --aspect-ratio "9:16" --prompt "<text>" --output <collection-path>/10-assets/short.png -y` | 9:16 縦型サムネ生成（Gemini） |
| `uv run yt-generate-shorts-loop <collection-path> -y` | `short.png` → 9:16 ループ動画 (Veo 3.1) |
| `uv run yt-generate-shorts-loop <collection-path> --prompt "..." -y` | カスタムプロンプトでループ生成 |

## Instructions

### Step 1: 既存の textless 動画背景 / 参考ビジュアルの確認

```bash
open <collection-path>/10-assets/main.*
```

シーンの構成要素（キャラクター・背景・小道具・カラー）を把握する。16:9 のクロップではなく **9:16 構図でゼロから再描写** するための参考とする。

### Step 2: プロンプト作成

`references/prompt-template.md` のテンプレートに沿って構築:

1. **冒頭**: `Tall vertical portrait composition.` を必ず明記
2. **シーン描写**: 既存の textless 動画背景 / 参考ビジュアルを参考に、9:16 縦長を活かして上下方向の環境ディテールを追加
3. **テキスト 3 層**（タイトル / チャンネル名 / CTA）の埋め込み指示
4. **スタイル句**: `references/prompt-template.md` の末尾テンプレを貼り付け

**構図の制約**:
- 斜め後ろ / 横顔推奨（カメラ目線 NG）
- キャラクターは画面中央〜やや下に配置（上部にテキスト空間確保）

詳細プロンプト例は `references/prompt-template.md` を参照。

### Step 3: 生成

```bash
export $(grep -v '^#' .env | xargs) && \
uv run yt-generate-image \
  --aspect-ratio "9:16" \
  --prompt "<Step 2 のプロンプト>" \
  --output <collection-path>/10-assets/short.png \
  -y
```

出力: `10-assets/short.png`（1536x2752）+ 自動生成 `short.jpg`

### Step 4: 確認・承認

```bash
open <collection-path>/10-assets/short.png
```

`AskUserQuestion` で承認 / 再生成を選ばせる。再生成時は `--output short-v2.png` のように自動バージョニング。

**チェック項目**:
- [ ] 9:16 縦型（1536x2752）
- [ ] テキスト 3 層がすべて読める
- [ ] 斜め後ろ / 横顔構図（カメラ目線 NG）
- [ ] 既存の textless 動画背景 / 参考ビジュアルとの世界観の一貫性
- [ ] 明るく鮮やかなカラー

### Step 5: ループ動画化（推奨）

承認された `short.png` を Veo 3.1 で 9:16 ループ動画に変換:

```bash
export $(grep -v '^#' .env | xargs) && \
uv run yt-generate-shorts-loop <collection-path> -y
```

カスタム動作プロンプトで微調整可:

```bash
uv run yt-generate-shorts-loop <collection-path> \
  --prompt "Gentle character animation: the woman slowly turns her head, hair sways in the breeze. Keep all text static and unchanged." \
  -y
```

出力: `10-assets/short-loop.mp4`（9:16、~7 秒、末尾 1 秒自動トリム）

```bash
open <collection-path>/10-assets/short-loop.mp4
```

**チェック項目**:
- [ ] テキストが崩れていない（3 層すべて読める）
- [ ] キャラクターが自然に動いている
- [ ] ループの継ぎ目が自然

## 設定

| 配置 | ファイル | 責務 |
|------|---------|------|
| ループ動画 skill 動作 | `.claude/skills/short-thumbnail/config.default.yaml`（あれば） | Veo モデル / プロンプト / クロップオフセット |
| チャンネル上書き | `config/skills/short-thumbnail.yaml` | skill-config 差し替え |

## Gotchas

- **`--aspect-ratio "9:16"` 必須**: 省略すると 16:9 で生成される
- **参照画像 (`--reference`) は使わない**: 16:9 構図に引っ張られるため。シーンを言葉で再描写する
- **CTA 文言の尺**: `config/channel/audio.json` の `audio.target_duration_min` を 60 で割って「Full N-hour collection」を埋める
- **コスト**: サムネは Gemini Flash 課金（事前見積もりは `config/skills/thumbnail.yaml` の `image_generation.<provider>.cost_per_image_usd` を指定したときのみ CLI 表示に出る。未指定なら GCP Cloud Console > Billing で実コスト確認）、ループ動画は Veo 3.1（別途課金、Vertex AI コンソールで確認）
- **Veo テキスト安定性**: プロンプトに `Keep all text completely static and unchanged` を含める。`last_frame=image` で開始 / 終了フレームのテキストを固定
- **Veo 末尾ノイズ**: 末尾 ~1 秒にノイズが入ることがある。`generate_short_loop.py` がデフォルトで末尾 1 秒をトリム

## ファイル構造

```
10-assets/
├── main.png          # 16:9 textless 動画背景 / 参考ビジュアル
├── thumbnail.jpg     # 16:9 テキスト付きサムネ（YouTube 用）
├── short.png         # 9:16 ショート用サムネ（本スキルで生成）
├── short.jpg         # 9:16 JPEG 版（自動生成）
├── short-loop.mp4    # 9:16 ループ動画（Step 5 で生成）
└── loop.mp4          # 16:9 ループ動画背景
```

## 長時間処理の取り扱い

`yt-generate-image`（Gemini で 9:16 サムネ生成、**10〜30 秒**）と `yt-generate-shorts-loop`（Veo 3.1 で 9:16 ループ動画、**30〜90 秒**）はどちらも API 同期呼び出しでブロックする。特にループ動画は長いため、**必ず Bash ツールを `run_in_background=true` で起動する**。これによりユーザーは処理中も同じセッションで質問できる（Claude Code は完了時に自動でメッセージ通知するため、`sleep` ループや `until` での自前ポーリングは禁止）。

spawn 例（ループ動画化）:

```bash
uv run yt-generate-shorts-loop <collection-path> -y \
  > /tmp/short-thumbnail-$(date +%s).log 2>&1
```

これを `Bash run_in_background=true` で投げ、spawn 直後に次のメッセージを返す:

> ⏳ Veo 3.1 で 9:16 ループ動画を生成中（推定 30〜90 秒）。完了まで他の質問にもお答えできます。
> ログ: /tmp/short-thumbnail-*.log

cmux 環境下（`$CMUX_WORKSPACE_ID` あり）であれば補助で `cmux set-status "short-thumbnail" "running" --icon "hourglass" --color "#f59e0b"`、完了で `cmux clear-status "short-thumbnail"` + `cmux notify --title "short-thumbnail 完了"` を呼ぶ（非 cmux 環境では skip）。

サムネ画像生成（Step 3 の `yt-generate-image`）は 10〜30 秒のため short 化判断はチャンネルポリシー次第だが、再生成を繰り返す運用なら同じ background パターンが安全。完了通知が届いたらログ末尾から結果サマリー（`short.png` / `short-loop.mp4` のパス）をユーザーへ返す。

## Next Step

`short.png` または `short-loop.mp4` が揃ったら:
→ `/short <collection-path>` でショート動画本体を生成・投稿
