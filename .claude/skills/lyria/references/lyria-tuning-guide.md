# Lyria Tuning Guide（参考資料）

Lyria RealTime API のパラメータ推奨値と、Test A-F 比較実験（2026-03-08）の結果サマリー。
実チャンネルでは `config/skills/lyria.yaml` で値を調整する。

## 推奨値サマリー

| パラメータ | 推奨値 | 根拠 |
|------|--------|------|
| `guidance` | **3.0** | 2.5 → pad 音増加（プロンプト忠実度不足）、3.5 → 音数過多 |
| `temperature` | **0.9** | 0.7 → メロディが単調ループ、0.6 以下 → ノイズ増 |
| `bpm` | **85-118** | 静かなフェーズ 88-95、活発なフェーズ 115-118。コントラストで動きを出す |
| `scale` | **C_MAJOR_A_MINOR** | ジャンルに合った音階を選択 |
| `mute_drums` | **true** | パーカッションなしの intimate サウンド |
| `prompt_prefix` | **最小限** | ジャンル + `acoustic instruments only` + `clean dry recording, no pads` 程度。楽器名・ムード語は入れない |
| ネガティブ指示 | `no pads` 程度 | 大量の `no X` は逆効果（概念を活性化する） |
| プロンプトスタイル | **動作指示** | 状態描写（sparse, intimate）→ ループ。動作指示（wandering, exploring, climbing）→ 展開 |

## NG ワード（汎用）

Lyria を ambient / cinematic 方向に引っ張る単語:

- `ambient pads` — NG
- `ethereal choir` — NG
- `cinematic` — NG
- `epic` — NG
- `synthesizer` — NG（アコースティック系で使う場合）

→ `config/skills/lyria.yaml` の `ng_words` に列挙しておき、プロンプトチェックで自動検出する。

## プロンプト設計の動作指示 vs 状態描写

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

雨音・環境音はプロンプトに含めない（Lyria が SE として解釈）。

- NG: `rain beginning to tap against old glass`
- OK: `solo piano, melody unfolding slowly, phrases breathing with the silence`

## 禁止形容詞（/suno と共通）

> thundering, blazing, crushing, soaring, screaming, devastating, explosive, ferocious, towering, surging, crystalline, shimmering, lush, sweeping, majestic, glorious, echoing

代替: low, sparse, bright, soft, deep, gentle, quiet, warm, airy, rising, driving
