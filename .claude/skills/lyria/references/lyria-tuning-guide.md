# Lyria Prompt Design Guide（参考資料）

Vertex AI Lyria 3 (`interactions` endpoint) の **プロンプト設計**の指針。
このリポジトリの `lyria_client.py` は現状 text prompt + model のみを API に渡すため、
音楽的なコントロールはすべてプロンプト文字列で行う。

> 注: このファイルには以前 `bpm` / `guidance` / `temperature` / `scale` / `mute_drums` 等の
> LiveMusicGenerationConfig パラメータ推奨値を掲載していたが、それらは Lyria RealTime API 専用で
> 現行 REST `interactions` 実装には無効なため削除済み。
> API 側は参照画像 / BPM / intensity / vocal-instrumental モードを受け取るが、
> このリポジトリの `lyria_client.py` は未対応（別 issue）。

## プロンプト設計原則

1. **prompt_prefix は最小限** — ジャンル + `acoustic instruments only` + `clean dry recording, no pads` 程度。楽器名・ムード語は入れない
2. **動作指示で書く** — 状態描写（sparse, intimate）ではなく、メロディの動き（wandering freely, climbing higher）を指示する
3. **形容詞は 1-2 個** — 詰め込みすぎると打ち消し合う
4. **ネガティブ指示は最小限** — `no pads` 程度で十分。大量の `no X` は逆効果（概念を活性化する）

## NG ワード（`config/skills/lyria.yaml` の `ng_words` に列挙）

Lyria を ambient / cinematic 方向に引っ張る単語:

- `ambient pads` — NG
- `ethereal choir` — NG
- `cinematic` — NG
- `epic` — NG
- `synthesizer` — NG（アコースティック系で使う場合）

## 動作指示 vs 状態描写

| 悪い例（状態描写 → ループ誘発） | 良い例（動作指示 → 展開誘発） |
|---|---|
| `solo fingerpicked guitar, sparse and intimate, unhurried and reflective` | `solo fingerpicked guitar, melody wandering freely in A minor, phrases rising and falling with varied rhythm` |
| `tin whistle, gentle and melancholic` | `tin whistle entering with ascending melody, each phrase exploring a new direction` |
| `fiddle, ornamental and warm` | `medieval fiddle melody climbing higher with each phrase, adding ornaments and turns` |

## 楽器切り替え式フェーズ設計

全楽器を同時に鳴らさず、フェーズごとに主役楽器を変える:

```
Phase 1: Solo Guitar    → wandering melody
Phase 2: Tin Whistle    → ascending melody (guitar underneath)
Phase 3: Fiddle Joins   → ornamental melody
Phase 4: All + Rest     → quiet afterglow
```

1-2 楽器が主役、他は伴奏に徹する。

## 環境音は NG

雨音・環境音はプロンプトに含めない（Lyria が SE として解釈し、メロディが崩れる）。

- NG: `rain beginning to tap against old glass`
- OK: `solo piano, melody unfolding slowly, phrases breathing with the silence`

## キーと調性のヒント

音階やキー（`A minor`, `D dorian`, `C major pentatonic` など）はプロンプト本文に含めると
Lyria が反映する。`config.default.yaml` の旧 `scale` enum は RealTime 専用なので無視してよい。

## 禁止形容詞（/suno と共通）

> thundering, blazing, crushing, soaring, screaming, devastating, explosive, ferocious, towering, surging, crystalline, shimmering, lush, sweeping, majestic, glorious, echoing

代替: low, sparse, bright, soft, deep, gentle, quiet, warm, airy, rising, driving
