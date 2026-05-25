---
name: community-draft
description: Use when YouTube コミュニティ投稿の下書きを生成したいとき。`--type` で behind-the-scenes / next-teaser / poll (deprecated) / day-of-reminder / weekly-feedback を切り替え、本文を生成して `pbcopy` でクリップボードに送る。「コミュニティ投稿作って」「community post」「day-of reminder」「sunday vote」「weekly feedback」「視聴者投票」「公開当日リマインダー」など、YouTube Studio に手動投稿するコミュニティ投稿の下書きが必要な場面で使用すること
---

## Overview

YouTube コミュニティ投稿の **下書き** を生成するスキル。
YouTube Data API v3 は Community 投稿に未対応のため、生成した本文を **`pbcopy` でクリップボードへ送り、YouTube Studio から人手で投稿する** 半自動運用を前提とする。

設定は `config/skills/community-draft.yaml`（任意。未指定なら同梱 `config.default.yaml`）と `config/channel/community-draft.json`（チャンネル固有のテンプレ上書き）を併用する。

## 前提

- `config/channel/` が存在すること（`load_config()` でロード可能）
- macOS 専用（`pbcopy` / `open` を利用）
  - Linux で動かす場合はクリップボード連携部分のみ無効化し、`30-promo/community-post-draft.md` の保存だけ行う
- YouTube Studio で投稿する想定（API 連携・自動投稿は本スキルの対象外）

`config/channel/` が存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## When to Use

- 公開当日のリマインダー投稿を作りたいとき
- 週次フィードバック（Sunday Vote 系）の投票投稿を作りたいとき
- 次コレクションの予告投稿を作りたいとき
- 公開後の制作裏側を共有したいとき

## `--type` フラグ

| `--type` | 状態 | 用途 |
|---|---|---|
| `behind-the-scenes` | 既存 | 公開当日 or 翌日の制作意図を一人称で共有 |
| `next-teaser` | 既存 | 次コレクションの予告（公開時期は曖昧に） |
| `poll` | **deprecated** | 旧 4 択投票（drink × animal_object 等）。`weekly-feedback` に置き換え |
| `day-of-reminder` | **新規** | 公開当日（数時間前）の視聴予約 + 通知設定リマインダー |
| `weekly-feedback` | **新規** | 週次 Sunday Vote。`theme_axis_pool` から N 軸を 4 択化して翌週テーマを投票 |

既存 type（behind-the-scenes / next-teaser）の細かい構造は **先行ダウンストリーム実装**（rjn の `config/channel/community-draft.json` 等）を参照し、本スキルは MVP として「同 type を扱える」フックを提供する。フル仕様化は別 issue。`poll` は deprecated（`weekly-feedback` へ移行済み）で、後方互換のため受理するのみ・新規利用は非推奨。

## 新規 type の表記ルール（重要）

issue #309 で確定した 2 表記の分離ルール:

- **投稿本文の時刻表記**: **24h 表記**
  - 例: `𝟏𝟖:𝟎𝟎 𝐄𝐃𝐓 / 𝟎𝟕:𝟎𝟎 𝐉𝐒𝐓`
  - 視聴者向け簡潔さ優先、jazzgak. 原典 `𝟏𝟖:𝟎𝟎 (𝐊𝐒𝐓/𝐉𝐒𝐓)` 形式を踏襲
  - 変数名: `{publish_time_24h_primary}` / `{publish_time_24h_secondary}`
- **draft 内の運用メモ・予約時刻**: **AM/PM 表記**
  - 例: `投稿 8:00-10:00 AM EDT`
  - YouTube Studio の予約投稿 UI が AM/PM 表記のためコピペ運用しやすくする
  - 変数名: `{schedule_window_local_ampm}` / `{schedule_time_ampm}`

skill 実装側で **必ず 2 表記を別変数として扱い、生成時点で分離** すること。本文中に AM/PM が混ざる、運用メモに 24h が混ざるのは NG。

## 出力先

```
<collection_dir>/30-promo/community-post-draft.md   # コレクション紐づき（day-of-reminder / behind-the-scenes / next-teaser）
branding/community-templates/<type>.md              # コレクション非紐づき（weekly-feedback）
```

保存後、`pbcopy < <出力ファイル>` で本文をクリップボードに送り、`open https://studio.youtube.com/channel/<channel_id>/community` で Studio を開く誘導を出す。

## `day-of-reminder` の構造

公開数時間前に投稿するリマインダー。`config.default.yaml::templates.day_of_reminder.structure` の順:

1. **headline** — 装飾フォント or プレーン文字で「今日公開 + 24h 時刻」を告知
   - 例（装飾）: `📢 𝐍𝐞𝐰 𝐝𝐫𝐨𝐩 𝐭𝐨𝐝𝐚𝐲 — 𝟏𝟖:𝟎𝟎 𝐄𝐃𝐓 / 𝟎𝟕:𝟎𝟎 𝐉𝐒𝐓`
   - 例（プレーン）: `📢 New drop today — 18:00 EDT / 07:00 JST`
2. **personal_mood** — 今日の天候・感覚的描写（1-2 行）
3. **creative_intent** — このコレクションで目指した雰囲気・小物の組み合わせ
4. **listening_cta** — 「今夜こんな風に聴いてほしい」の柔らかい誘導
5. **notification_cta** — 通知設定（🔔 + 😘）
6. **gratitude** — 感謝（🤍）
7. **signature** — チャンネル署名（装飾フォント可）

末尾に Premiere URL を貼ると Studio が自動でカード化する（別途「動画を添付」操作不要）。

## `weekly-feedback` の構造

毎週日曜に投稿する 4 択ポール。`config.default.yaml::templates.weekly_feedback`:

- `theme_axis_pool`: チャンネルの主要 theme 軸を N 個定義（rjn は 5 軸、汎用では `[]` 空配列スタート）
- `rotation_rule.present_count`: 毎週提示する選択肢数（`auto` = `axis_count - 1`）
- `rotation_rule.cycle_weeks`: 1 周にかかる週数（`auto` = `axis_count`）
- `schedule_window_local_ampm`: Studio 予約時刻ガイド（AM/PM 表記）

本文構造:

1. **headline** — 装飾フォント or プレーン（例: `📢 Sunday vote — what's next week?`）
2. **opener** — 週末オープナー 1 文 + theme emoji
3. **intent** — 「あなたの mood を追いかけたい」型の制作意図
4. **poll** — N-1 択（`theme_axis_pool` から `rotation_rule` で選定）
5. **promise** — 「投票結果が来週の制作に反映される」約束
6. **notification_cta** — 通知設定（🔔 + 😘）
7. **gratitude** — 感謝（🤍）
8. **signature** — チャンネル署名

> Studio 側で「アンケート付き投稿」を選択し、`poll` 段落の 4 択を **手動で** ポール選択肢に入力する。本文には選択肢を含めない or 重複表示してもよい（運用判断）。

## 実行フロー（概要）

1. `--type` を判定（未指定なら interactive にユーザーに尋ねる）
2. 該当 type の `config.default.yaml` ブロックと `config/channel/community-draft.json` の override をマージ
3. テンプレ変数を解決
   - `day-of-reminder`: コレクション `workflow-state.json` から公開日時 / scene_phrase / drink 等を引く
   - `weekly-feedback`: `data/community/weekly-vote-log.json`（存在すれば）の直近履歴から提示 4 択を選定
4. 本文を生成し `30-promo/community-post-draft.md` または `branding/community-templates/<type>.md` に保存
5. `pbcopy` でクリップボードへ送り、Studio を `open` で開く案内を出す

## 配布されるサンプル

`examples/community-draft-rjn/` に rjn 実例を **reference のみ** として収録（デフォルト config には反映されない）:

- `rain-5-axis.yaml` — rjn の 5 軸 axis_pool 構造
- `day-of-reminder-cloudwalk.md` — 当日リマインダー本文例

ダウンストリームが「真似て自分のチャンネル軸に書き換える」ためのテンプレ。

## スコープ外（follow-up #339 で扱う）

- `/collection-ideate` への vote-log hook（`data/community/weekly-vote-log.json` の `top_axis` を theme weight に取り込む）
- `data/community/weekly-vote-log.json` スキーマの正式化
- 既存 type（behind-the-scenes / next-teaser）のフル仕様化

## 参考

- issue #309（本スキル新設）
- rjn 実装: `config/channel/community-draft.json` / `branding/community-templates/weekly-feedback.md` / `collections/live/20260515-rjn-cloudwalk-collection/30-promo/community-post-draft.md`
- 流派: jazzgak. TTP（韓国系 lo-fi jazz × 雨音、ER 平均 2.68%）
