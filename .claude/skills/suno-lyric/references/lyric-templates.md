# Suno V5.5 歌詞テンプレート集（`/suno-lyric` 用）

`/suno-lyric` が **名言エッセンス → Suno V5.5 歌詞** に再構築するときの構造テンプレ。
Suno UI の Lyrics 入力欄プレースホルダ（公式案内）の形式に準拠。

## Suno V5.5 セクションタグ

Suno UI が認識するセクションタグ:

- `[Intro]` — 短い導入。器楽 or 1-2 行のスポークン
- `[Verse]` — 物語・描写を運ぶ。4-6 行が標準
- `[Pre-Chorus]` — Chorus への助走（オプション）
- `[Chorus]` — フック。短く・反復可能・覚えやすい
- `[Bridge]` — 視点シフト or 感情ピーク。1 曲に 1 つ
- `[Instrumental break]` — 完全な楽器のみ区間。Bridge の代替
- `[Outro]` — 余韻。短い 1-2 行 or fade

セクションタグは **角括弧 `[]` でラップ**。1 行 1 タグ。タグの後ろは空行を入れずに歌詞本文を続けるのが Suno 流。

---

## 標準テンプレ（4 種）

以下は Funk/Soul ジャンル + 大人向けペルソナの例。チャンネル固有の `docs/channel/personas/persona-definition.md` がある場合は、そちらの語彙と視聴シーンを優先する。旧 `docs/audience-persona.md` は legacy fallback としてのみ参照する。

### Template A: Smooth Soul（mid tempo 95-110 BPM）

**用途**: 標準的な smooth groove。コレクションの過半数はこのテンプレでよい。

```
[Verse]
1: 情景描写（視覚 or 触覚） — 4-7 words
2: 1 と韻を踏む or 並列イメージ — 4-7 words
3: 内面に少し踏み込む — 4-7 words
4: 3 と韻 — 4-7 words

[Chorus]
1: フック決め台詞 — 3-5 words
2: 1 のリフレーズ or 補強 — 3-5 words
3: フックを別角度から — 3-5 words
4: 1 とほぼ同じ or 反復 — 3-5 words

[Verse]
（Verse 1 と同じ構造、視点を少し変える）

[Chorus]
（繰り返し）

[Bridge]
1: 名言エッセンスをここで直接的に表現 — 5-8 words
2: 1 の余韻 / 結論 — 5-8 words

[Chorus]
（最終リフレイン）

[Outro]
1: 1 行で締める or instrumental fade — 短く
```

#### 実装例（架空・Maya Angelou エッセンス由来）

エッセンス: "What we made each other feel is the only thing that stays."

```
[Verse]
Sunlight on the kitchen floor
Coffee cup, the morning slow
What you said I half forgot
But how it felt, that I still know

[Chorus]
Only feelings stay
Only feelings stay
Words fade like the day
But only feelings stay

[Verse]
Photographs are turning gold
Names are slipping through my mind
Some warm hand from years ago
Still around, I always find

[Chorus]
Only feelings stay
Only feelings stay
Words fade like the day
But only feelings stay

[Bridge]
The room remembers what we did not say
The light remembers every shade of day

[Chorus]
Only feelings stay
Only feelings stay

[Outro]
(stay, stay, stay…)
```

### Template B: Slow Soulful Ballad（slow 80-95 BPM）

**用途**: しっとり・夜・内省。1 行が長め。

```
[Verse]
1: 長い情景描写 — 6-9 words
2: 1 と緩く韻 — 6-9 words
3: 体感・温度 — 6-9 words
4: 3 と韻 — 6-9 words

[Chorus]
1: フック — 5-7 words
2: 1 の延長 — 5-7 words
3: 別角度 — 5-7 words
4: リフレイン — 5-7 words

[Verse]
（同上、時間が経過した感覚）

[Chorus]
（繰り返し）

[Bridge]
1: 名言エッセンスの心理描写 — 7-10 words
2: 諦観 or 受容 — 7-10 words

[Chorus]
（最終）

[Outro]
1 行 or instrumental fade
```

### Template C: Up-tempo Funky Groove（up 110+ BPM）

**用途**: 踊れる・陽気・good times 系。短い行で押韻を強く。

```
[Verse]
1: シャープな描写 — 3-5 words
2: 1 と完全韻 — 3-5 words
3: 動詞中心 — 3-5 words
4: 3 と完全韻 — 3-5 words
5: 1-2 を補強 — 3-5 words
6: フックへの助走 — 3-5 words

[Chorus]
1: 短いフック — 2-4 words
2: 1 の反復 — 2-4 words
3: 別語の同義 — 2-4 words
4: 1 とほぼ同じ — 2-4 words

[Verse]
（同構造、別シーン）

[Chorus]
（繰り返し）

[Instrumental break]
（楽器のみ区間。Bridge の代わりに使うと踊りを切らない）

[Chorus]
（×2 で終える）

[Outro]
1 行 + fade
```

### Template D: Pre-Chorus 付き拡張型（厚みを出したい曲用）

**用途**: Verse と Chorus の橋渡しに Pre-Chorus を入れて期待感を作る。

```
[Verse]
4 行

[Pre-Chorus]
2-3 行 — Chorus への期待を高める短い区間

[Chorus]
4 行

[Verse]
4 行

[Pre-Chorus]
2-3 行

[Chorus]
4 行

[Bridge]
2-3 行 — 名言エッセンスの核を表出

[Chorus]
4 行（最終）

[Outro]
1 行 or fade
```

---

## 押韻パターン（4 種）

各 Verse / Chorus 内で 1 つ選ぶ。

### abab（クロス韻）

```
1: ...... road  (a)
2: ...... slow  (b)
3: ...... home  (a)
4: ...... go    (b)
```

### aabb（連続韻 / カップレット）

```
1: ...... light (a)
2: ...... night (a)
3: ...... day   (b)
4: ...... stay  (b)
```

### abba（包囲韻）

```
1: ...... time  (a)
2: ...... wide  (b)
3: ...... ride  (b)
4: ...... mine  (a)
```

### 無韻 + 反復（モダンソウル系）

押韻にこだわらず、語尾の母音やキーワード反復で繋ぐ。Bridge に最適。

---

## 推奨語彙（Carla 層 + Funk/Soul 系統）

### よく使う情景語

- **空間**: room, kitchen, doorway, window, street, basement, backroom, midnight diner
- **光**: lamp, neon, sunlight, candle, golden, glow, fade
- **触感**: warm, smooth, slow, breath, hand, skin, breeze
- **時間**: midnight, dawn, summer, year, hour, slow, then, used to
- **音**: bassline, hum, whisper, radio, record, vinyl

### 動詞（モダンソウル定番）

- carry, hold, stay, lean, breathe, drift, keep, remember, fade, glow, slip

### 押韻ペアの定番

- `night` / `light` / `right` / `tight`
- `way` / `stay` / `day` / `say` / `away`
- `slow` / `know` / `go` / `flow`
- `time` / `mine` / `line` / `shine`
- `home` / `alone` / `own` / `bone`

---

## 禁止語彙（AI 臭の代表）

`config.lyric.vocab_constraints.avoid` と連動:

- `yo` / `ay` / `uh` / `yeah yeah` / `y'all`
- `let me tell ya` / `baby baby baby`
- `oh oh oh` / `na na na`（exception: Outro のフェード fade 部分なら可）
- Z 世代スラング（`vibe check` / `slay` / `lit` 等）

---

## 名言 → 歌詞 変換の具体例

### Example 1: Bob Marley（groove テーマ）

**選定名言**: "Don't worry about a thing, 'cause every little thing gonna be alright."
**エッセンス**: "Every small thing finds its way."

**Template A で展開（英語）**:

```
[Verse]
Streetlight flickers on the corner
Old jukebox plays the same slow tune
Don't need a map to find tomorrow
Every step will lead us home soon

[Chorus]
Every little thing will find its way
Every little thing will find its way
Take it easy, take it slow today
Every little thing will find its way

[Verse]
Lost my keys, but found the moonlight
Got the radio, that's all I need
Worries lift up like the morning
Slowly, gently, like a freed bird

[Chorus]
Every little thing will find its way
...

[Bridge]
The river knows where it is going
We just float and breathe along

[Chorus]
...

[Outro]
(finds its way…)
```

**Lyrics (Japanese / 意訳)**:

```
[Verse]
街灯が角でちらついて
古いジュークボックスが同じ曲を流す
明日への地図はいらない
どの一歩も、ちゃんと家へ続く

[Chorus]
どんな小さなことも、流れていく
どんな小さなことも、流れていく
今日はゆっくり、急がずに
どんな小さなことも、流れていく

[Verse]
鍵をなくして、月明かりを見つけた
ラジオがあれば、それでいい
朝みたいに、心配は浮き上がる
ゆっくり、やさしく、放たれた鳥のように

[Chorus]
（繰り返し）

[Bridge]
川は、自分の行き先を知っている
僕らはただ、浮かんで、息をしているだけ

[Chorus]
（繰り返し）

[Outro]
（流れていく…）
```

**和訳の判定ポイント**:
- 「Don't worry」を「心配ない」と直訳せず、「流れていく」で受容のニュアンスに置換
- Chorus の反復性を残しつつ、1 行 6-14 文字でフックの覚えやすさを維持
- Carla 語彙の `slow → ゆっくり`、`way → 流れていく` を活用

### Example 2: Maya Angelou（nostalgia テーマ）

**選定名言**: "I've learned that people will forget what you said, people will forget what you did, but people will never forget how you made them feel."
**エッセンス**: "Only the feeling stays."

**英語実装**: 「Template A: Smooth Soul」セクションの実装例（Only feelings stay）参照。

**Lyrics (Japanese / 意訳)**:

```
[Verse]
台所の床に陽が落ちている
コーヒーカップ、ゆっくりした朝
あなたの言葉は、半分忘れた
でも、どう感じたかは、今も覚えてる

[Chorus]
気持ちだけが残る
気持ちだけが残る
言葉は日のように消えていくけど
気持ちだけが残る

[Verse]
写真は金色に変わってきて
名前は記憶からこぼれていく
何年も前の、あの温かい手のひら
今もまだ、すぐ近くにある

[Chorus]
（繰り返し）

[Bridge]
あの部屋は、言えなかった言葉を覚えている
光は、ひとつひとつの色合いを覚えている

[Chorus]
（繰り返し）

[Outro]
（残る、残る、残る…）
```

**和訳の判定ポイント**:
- 「forget what you said」を「言葉は半分忘れた」と意訳。逐語訳「あなたが言ったことを忘れた」を避け、Carla の語り口に近づける
- `golden` → 「金色に変わってきて」で写真の経年変化として自然化
- Chorus の `Only feelings stay` は「気持ちだけが残る」で固定し、英語側の反復性に対応
- Outro の `stay, stay, stay…` は「残る、残る、残る…」で音節の数も合わせる

---

## 検証時のセルフチェック項目

生成後、自分の歌詞を以下でレビュー:

### 英語側

- [ ] セクション構造が揃っているか（Verse 2 + Chorus 2 + Bridge or Break 1 最小）
- [ ] 1 行の単語数がテンポガイドに沿っているか
- [ ] `avoid` 語彙が混入していないか
- [ ] 名言原文の連続 5 単語以上の直接コピーが無いか
- [ ] gender 一貫性（主語・人称代名詞）
- [ ] Carla 層への適合度（"懐かしい・本物・静かな自信" のいずれかが感じ取れる）
- [ ] AI 臭の代表症状（オウム返し・空疎な決め台詞・過度な感嘆詞）が無いか

### 和訳側

- [ ] セクションタグが英語側と一致しているか（`[Verse]` / `[Chorus]` / `[Bridge]` / `[Outro]`）
- [ ] 翻訳臭の語（「〜という意味」「Verse 1 では」「ここで」等）が含まれていないか
- [ ] Chorus が英語側と同じ回数反復されているか
- [ ] Chorus の 1 行が 6-14 文字に収まっているか（フックの覚えやすさ）
- [ ] 逐語訳になっていないか（英語の語順を引きずっていない / 「私は〜」を多用していない）
- [ ] 散文の説明文ではなく「歌詞として読める」形式になっているか
- [ ] Carla 語彙の日本語版（金色の・残る・静かな・焦がれる 等）が活きているか
- [ ] 「いい歌詞かどうか判定する」という用途を満たすか（英語が分からない人が日本語側だけ読んでも世界観が立ち上がる）
