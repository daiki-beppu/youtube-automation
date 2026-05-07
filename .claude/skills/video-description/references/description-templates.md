# description スキル テンプレート集

`description` スキルが出力する YouTube 概要欄のテンプレート本文と、コレクション内 `descriptions.md` の保存フォーマットをまとめる。

テンプレート更新時はこのファイルのみを編集すれば SKILL.md 本体は差し替え不要。

---

## Complete Collection 概要欄テンプレート

BGM チャンネル向けにアダプトした、情景フック＋タイムスタンプ＋Perfect for 構成のテンプレート。

```
[絵文字装飾]. [情景フック — 詩的な1行。コレクションの世界に引き込む]
[音楽の誘い — リスナーへの語りかけ1行] [絵文字]

[音楽の特徴 — 2行で楽器・ムード・雰囲気を描写]

- Genre : [ジャンル名, サブジャンル]
- Vibe : [形容詞4つ]
- Best for : [用途4つ]



⎯⎯⎯⎯⎯✦ ⋆˚ 𝙈𝙪𝙨𝙞𝙘 𝙏𝙞𝙢𝙚 ⋆˚✦⎯⎯⎯⎯⎯

💽 [コレクション名 — 英語ボールド Unicode]

00:00 [Track/Chapter 1]
XX:XX [Track/Chapter 2]
...


🎧 If you enjoyed the vibe, feel free to save and subscribe for more 🌧️
🔔 {channel_config: channel.cta_subscribe}

{channel_config: channel.url}


⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
🎨 𝐀𝐫𝐭 & 🎹 𝐌𝐮𝐬𝐢𝐜 𝐛𝐲 {channel_config: channel.name}
• Original AI composition • Free for personal use
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯



{channel_config: descriptions.hashtags}
```

### テンプレートのポイント

- 冒頭は **詩的な情景** + **リスナーへの語りかけ**（YouTube の折りたたみ前に表示される）
- メタデータは `Genre / Vibe / Best for` の3行（検索性 + 一目で内容がわかる）
- タイムスタンプセクションは装飾付きヘッダー（`⎯⎯✦ ⋆˚ Music Time ⋆˚✦⎯⎯`）
- CTA は短く温かい語調（「保存＆登録」をさりげなく）
- クレジットは最小限（Art & Music by）
- ハッシュタグは最後にまとめて配置

---

## descriptions.md 保存フォーマット

概要欄生成結果はコレクションの `20-documentation/descriptions.md` に以下の構成で保存する。

````markdown
# [Collection Name] — YouTube 概要欄

*生成日: YYYY-MM-DD*
*トラック数: N / 総時間: Xh Xm Xs*

---

## Complete Collection 概要欄

```
[概要欄本文]
```

---

## タイトル案

```
[タイトル]
```

---

## タグ（YouTube タグ欄）

```
[タグリスト]
```

---

## Cards (YouTube Studio で手動設定)

```
Card ([タイミング]): "[ティーザーメッセージ]" → [リンク先動画タイトル]
```

---

## 品質チェック

- [x] 誇張表現なし
- [x] AI 透明性あり
- [x] チャンネル CTA 含む
- [x] ハッシュタグ 13個
- [x] モバイル読みやすさ
- [x] カードセクション含む
````
