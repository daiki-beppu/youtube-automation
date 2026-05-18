# day-of-reminder 実例 — Rain Jazz Night / Cloudwalking Pavlova Hours

> このファイルは upstream のデフォルトには反映されない **reference**。
> ダウンストリームが `/community-draft --type day-of-reminder` の出力を
> 「真似て自分のチャンネル文脈に書き換える」ための雛形。
>
> 流派: jazzgak. TTP（海外向け英語版）
> 装飾フォント: Mathematical Bold sans-serif (`decorative_font: true`)
> 投稿タイミング: 公開 **12h 前** 固定（毎日投稿運用のリズム化）
>   - 例: 公開 5/16 6:00 PM EDT → 投稿 5/16 6:00 AM EDT
> 投稿先: YouTube Studio（API 非対応のため手動）

---

## 投稿本文（コピペ用、24h 表記）

```
📢 𝐍𝐞𝐰 𝐝𝐫𝐨𝐩 𝐭𝐨𝐝𝐚𝐲 — 𝟏𝟖:𝟎𝟎 𝐄𝐃𝐓 / 𝟎𝟕:𝟎𝟎 𝐉𝐒𝐓

The sky's been doing that soft, cotton-candy drift all day, and I couldn't help but pour it into a track. ☁️

This one's for the kind of evening where you'd rather float than push — a pavlova nest on the table, a butterfly-pea soda fizzing slowly, and rain tapping just gently enough to keep you company.

Save this post as a quiet little reminder. When tonight rolls around, brew something warm, open the page you've been meaning to read, and let the Rhodes carry you a few inches above the ground.

(Turn on Notifications 🔔 so it finds you the moment it goes live — and if it takes you somewhere good, a Like and a Subscribe mean the world. 😘)

Thank you for staying with me, always. 🤍

– 𝐑𝐚𝐢𝐧 𝐉𝐚𝐳𝐳 𝐍𝐢𝐠𝐡𝐭

▶ Premiere link: https://www.youtube.com/watch?v=XXXXXXXXXXX
```

---

## 運用メモ（AM/PM 表記、Studio UI 整合）

- **投稿予約時刻**: 公開 12h 前の **6:00 AM EDT** = **7:00 PM JST**
  - 毎日投稿運用なら投稿時刻も固定し、視聴者の期待リズムを定着させる
- **Studio 操作手順**:
  1. YouTube Studio → 左メニュー「コミュニティ」→「投稿を作成」
  2. 上記本文をコピペ（`pbcopy` で自動化される）
  3. 本文末尾の Premiere URL は **自動でカード化される**（別途「動画を添付」は不要）
  4. 投稿時刻を指定したい場合は公開予約を有効化
- **装飾フォントの注意**: Mathematical Bold sans-serif は Studio エディタで一部欠ける可能性あり。
  プレビューで欠けていたらこの md からコピペし直すか、`decorative_font: false` で再生成する

---

## 構造解説（テンプレ流用時に保持すべき骨格）

| セクション | 役割 | 装飾 |
|---|---|---|
| `headline` | 当日 + 24h 時刻告知 | 装飾フォント + 📢 + 24h 表記 |
| `personal_mood` | 今日の天候・身体感覚（1-2 行） | プレーン + 1 絵文字 |
| `creative_intent` | 楽曲で目指した雰囲気・小物（pavlova / butterfly-pea soda 等） | プレーン |
| `listening_cta` | 「今夜こんな風に聴いてほしい」誘導 | プレーン |
| `notification_cta` | 通知設定（🔔 + 😘） | カッコ書きで控えめに |
| `gratitude` | 感謝（🤍） | 短く |
| `signature` | 署名 + Premiere URL | 装飾フォント可 |

中央 3 段落（mood / intent / cta）だけコレクション別に差し替え、冒頭ヘッダーと末尾 2 段落は固定テンプレ
として毎日流用するのがリズム化のコツ。

---

## TTP 元

jazzgak. の `𝐒𝐞𝐞 𝐲𝐨𝐮 𝐭𝐨𝐝𝐚𝐲! 𝟏𝟖:𝟎𝟎 (𝐊𝐒𝐓/𝐉𝐒𝐓)` 当日告知型を、
Maya 北米想定向けに EDT 主軸へ翻訳。CTA 構造
（時刻告知 → 個人的気分 → 制作意図 → 視聴 CTA → 通知設定 CTA → 感謝 → 署名）はそのまま継承。
