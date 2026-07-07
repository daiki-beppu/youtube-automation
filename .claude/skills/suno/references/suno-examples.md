# SunoAI プロンプト例（参考資料）

品質が高い情景フレーズ + スタイルプロンプトの参考例。
**これは例示のみ** — 各チャンネルの `config/skills/suno.yaml` の `genre_line` + `style_variants` に合わせて調整すること。

## 例 1: jazzhop / lo-fi 系

### 品質基準プロンプト（C-1 パターン）

```
chill jazz hop, dusty piano samples, jazzy guitar licks, deep bass groove,
bass-forward mix, prominent upright bass, lo-fi drum loop, tape saturated,
instrumental, gentle, moody and misty, no rain sound effects, no white noise,
no ambient noise,
glistening cobblestone sidewalk at night, a bookshop awning glowing softly
```

**成功要因**:
- ベースが前面に出ており、BGM としての厚みがある
- `moody and misty` でしっとり感を確保しつつ雨 SE なし
- `tape saturated` でアナログの温かみ（`vinyl crackle` は NG — ノイズ SE を誘発）
- 情景フレーズが視覚的で音を連想しない

## 例 2: acoustic folk / celtic 系

```
celtic folk, acoustic guitar fingerpicking, tin whistle melody, gentle fiddle,
warm hearth recording, instrumental, unhurried,
morning mist rising between ancient oaks, a stone well at the crossroads
```

## 例 3: ambient piano 系

```
solo piano, felt piano texture, minimal reverb, intimate microphone,
instrumental, sparse and reflective,
snow falling outside a library window, a half-finished teacup on the desk
```

## Style 自動バリエーションの例（#1456）

同一コレクション内で `genre_line` は共通のまま、entry ごとに texture / rhythm feel の descriptor が
Style 第 1 行末尾へ決定的に付与される（先頭 entry は base のまま）:

```
# entry 1 (base)
slow, lo-fi jazz, soft piano, warm rhodes,
a quiet rooftop at dawn

# entry 2
slow, lo-fi jazz, soft piano, warm rhodes, laid-back rhythm feel,
grey smoke trailing upward from a rooftop chimney

# entry 3
gentle, lo-fi jazz, soft piano, warm rhodes, warm rounded texture,
a single paper lantern swaying above a narrow alley
```

descriptor はジャンルを変えない形容詞句に限定する。禁止形容詞・雨音 NG ワードは pool に入れないこと。

## 情景フレーズ設計の共通原則

1. **命令文なし**: "Create a..." で始めない
2. **簡潔な修飾**: 形容詞は 1-2 個
3. **五感に訴える**: 視覚・触覚・嗅覚の具体描写（メロディ・リズムは書かない）
4. **楽器ロール指定（任意）**: `Solo Cello`, `Ethereal Choir` でフィーチャー楽器を強調可能

## 禁止形容詞（全チャンネル共通）

SunoAI をモダン/オーケストラ方向に誘導するため禁止:

> thundering, blazing, crushing, soaring, screaming, devastating, explosive, ferocious, towering, surging, crystalline, shimmering, lush, sweeping, majestic, glorious, echoing

代替: low, sparse, bright, soft, deep, gentle, quiet, warm, airy, rising, driving

## 雨音・環境音の制御（全チャンネル共通）

雨音・環境音は**楽曲に含めない**。マスタリング時に別レイヤーで追加する。

**NG ワード（SE を誘発）:**
> rain, dripping, drops, puddles, splashing, pouring, streaming water, trickling

**OK ワード（ムード・視覚のみ）:**
> misty, melancholic, nocturnal, bittersweet, wistful, lonesome, overcast, hazy, foggy, damp, glistening, misted, fogged

**全プロンプト末尾に追加:**
```
no rain sound effects, no white noise, no ambient noise
```

**Exclude Styles にも追加:**
```
rain sounds, vinyl crackle, white noise, ambient noise
```

## Instrument Adjective Pairs (Bad/Good)

楽器名だけでは Suno の生成が不安定になる。必ず音響的な形容詞を付けること（`config/skills/suno.yaml::banned_adjective_free_instruments` に該当する楽器名は `bunx tayk generate-suno` が警告する）。

| Bad (vague) | Good (descriptive) |
|---|---|
| guitar | fingerpicked acoustic guitar |
| piano | felt-damped upright piano |
| bass | deep fretless bass |
| drums | brushed jazz drums |
| synth | warm analog synth pad |
| strings | lush chamber strings |
| trumpet | muted jazz trumpet |
| flute | breathy wooden flute |
| organ | vintage Hammond organ |
| cello | bowed solo cello |

> **原則**: 楽器名に最低 1 つの修飾語（音色・奏法・素材・時代）を付ける。Style 欄で楽器を裸で書くと Suno が汎用音色を選択し、意図した音像から外れる。
