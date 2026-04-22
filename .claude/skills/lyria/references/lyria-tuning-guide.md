# Lyria Prompt Design Guide（参考資料）

Vertex AI Lyria 3 (`interactions` endpoint) の **プロンプト設計** の指針。
`lyria_client.py` は text prompt に加えて、参照画像・BPM・intensity・vocal/instrumental mode・lyrics を受け取れる。
API 仕様上の真の構造化入力は参照画像のみで、他は自然言語プロンプトに合成される（`_compose_prompt`）。

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

## 参照画像による雰囲気注入

`reference_image` を指定するとサムネイルの色調・質感が音源に反映される（Lyria 3 の唯一の構造化入力）。

- 推奨: コレクションの `main.png` (PNG, 1280×720 以上)。composition.json から見て `../10-assets/main.png`
- 対応形式: `.png` / `.jpg` / `.jpeg` / `.webp`
- 暗い画像 → minor key / muted tones に寄る傾向、明るい画像 → major key / bright timbre に寄る傾向
- **プロンプトとの整合が重要**: 強すぎる画像（色のコントラストが激しいもの）はメロディ指示より色調優位に働く。プロンプト側でも同じ雰囲気を言語化する
- phase ごとに異なる画像を使うこともできる（`phases[].reference_image`）。ストーリー性のある曲構造を作りたい場合に有効

## BPM / intensity の使い分け

BPM は自然言語プロンプトに `", {bpm} BPM"` として合成される。表記揺れ（"around 120 bpm" / "fast tempo" 等）より構造化指定のほうが安定。

- BPM 目安: 60-90 ambient/ambient folk / 90-110 medium / 110-140 driving / 140-180 high-energy
- チャンネル一貫性のため `config/skills/lyria.yaml` の `default_bpm` にチャンネル共通値を設定するとよい

`intensity` は `"low"` / `"medium"` / `"high"` の 3 値に集約される:

| Literal | 合成される英語句 |
|---|---|
| `"low"` | `"mellow, low-energy"` |
| `"medium"` | `"balanced, moderate energy"` |
| `"high"` | `"driving, high-energy"` |

プロンプト冒頭に prepend されるため、全体のムードを左右する。formidable adjectives の代わりにこれを使うと禁止形容詞リストにも抵触しない。

## vocal / instrumental モードと lyrics

デフォルトは instrumental 推奨（BGM チャンネルでは歌声は情景と合わないことが多い）。

- `mode: "instrumental"` → プロンプト末尾に `". Instrumental."` が付く。Lyria 3 が強く反応するキーフレーズ
- `mode: "vocal"` + `lyrics` 未指定 → `". With vocals."` が付く。AI が歌詞を自動生成
- `lyrics: "..."` → プロンプト末尾に `". Lyrics: ..."` が付く。`[Verse]` `[Chorus]` の section tag を使って構造指定可能
- `mode: "vocal"` + `lyrics` 併用時は `"With vocals"` を省略（lyrics が vocal モードを含意する）

DJ 型コレクションで特定 phase のみ vocal にしたい場合は `phases[].mode: "vocal"` + `phases[].lyrics: "..."` で phase 単位切替。
