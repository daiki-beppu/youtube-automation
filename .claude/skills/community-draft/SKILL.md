---
name: community-draft
description: "Use when YouTube コミュニティ投稿の下書きを生成したいとき。`--type` で behind-the-scenes / next-teaser / poll (deprecated) / day-of-reminder / weekly-feedback を切り替え、本文を生成して `pbcopy` でクリップボードに送る。「コミュニティ投稿作って」「community post」「day-of reminder」「sunday vote」「weekly feedback」「視聴者投票」「公開当日リマインダー」など、YouTube Studio に手動投稿するコミュニティ投稿の下書きが必要な場面で使用すること"
---

## Overview

YouTube コミュニティ投稿の **下書き** を生成するスキル。
YouTube Data API v3 は Community 投稿に未対応のため、生成した本文を **`pbcopy` でクリップボードへ送り、YouTube Studio から人手で投稿する** 半自動運用を前提とする。

設定は `config/skills/community-draft.yaml`（任意。未指定なら同梱 `config.default.yaml`）と `config/channel/community-draft.json`（チャンネル固有のテンプレ上書き）を併用する。

## 設定読み込みゲート

前提確認やテンプレート生成に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/community-draft/config.default.yaml`
2. `config/skills/community-draft.yaml`（存在する場合）

読み込み後は `youtube_automation.utils.skill_config.load_skill_config("community-draft")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。この skill-config とは別に、必要な `config/channel/community-draft.json` は既存手順どおり読む。

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
| `behind-the-scenes` | フル仕様化済み | 公開当日 or 翌日の制作意図を 4 文構造で一人称共有 |
| `next-teaser` | フル仕様化済み | 次コレクションの予告（次の `workflow-state.json` を参照） |
| `poll` | **DEPRECATED (#509)** | 旧 4 択投票。`weekly-feedback` に正式 retire 済み |
| `day-of-reminder` | 既存 | 公開当日（数時間前）の視聴予約 + 通知設定リマインダー |
| `weekly-feedback` | 既存 | 週次 Sunday Vote。`theme_axis_pool` から N-1 軸を提示し翌週テーマを投票 |

issue #509 で `behind-the-scenes` / `next-teaser` は upstream 仕様化が完了した（後述の各セクション参照）。`poll` は **DEPRECATED**: `utils.weekly_vote_log.warn_poll_deprecated()` が `logger.warning` を吐く実装で正式 retire 済み。後方互換のため受理はするが新規利用は禁止し、`weekly-feedback` に移行すること。

### `poll` から `weekly-feedback` への移行ガイド

| 旧 (`poll`) | 新 (`weekly-feedback`) |
|---|---|
| 4 択固定 (drink × animal_object) | `theme_axis_pool` 上の任意 N 軸 → `rotation_rule.present_count` (`auto` = N-1) で動的提示 |
| 投票結果の記録なし | `data/community/weekly-vote-log.json` に週次保存。`yt-vote-log append` で記録 |
| `/collection-ideate` への反映なし | hook 経由で直近 N 週の `top_axis` を theme weight に取り込む |

`config/channel/community-draft.json` で `templates.poll.enabled: true` が残っている場合は `templates.weekly_feedback.enabled: true` + `theme_axis_pool` を移植してから `poll` を削除する。

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

## `behind-the-scenes` の構造（#509 で upstream 化）

公開当日 or 翌日に投稿する、制作裏側を **一人称 4 文** で共有する短文投稿。
`config.default.yaml::templates.behind_the_scenes` の構造順:

1. **scene_hook** — 1 文目: 制作中に見えていた / 聞こえていた具体的情景を 1 つ提示
   - 例: `窓に当たる雨の音をずっと録ってました。`
   - 変数: `{scene_phrase}` (コレクション `workflow-state.json::planning.scene_phrase`)
2. **mood_anchor** — 2 文目: そのときの自分の mood (静か / 焦り / うとうと等を 1 表現)
   - 例: `深夜 3 時、半分まどろみながら。`
   - 変数: `{personal_mood}`
3. **signature_element** — 3 文目: コレクション固有の small object / 音 / 飲み物に触れる
   - 例: `カップは {drink_signature}、奥で揺れる {animal_object} が今回の主役。`
   - 変数: `{drink_signature}` / `{animal_object}` (channel-config の `objects.swappable` から解決)
4. **listening_invitation** — 4 文目: 「こう聴いてほしい」の柔らかい誘導 + Music style 言及
   - 例: `{music_style} の質感を、夜だけのプレイリストに入れてもらえたら。`
   - 変数: `{music_style}` (content.json::genre.label 由来)

末尾に通知 CTA (`🔔 + 😘`) と感謝 (`🤍`) を付与し、署名は `signature_template` に従う。
**フォーマットルール**:

- 4 文は段落区切り (1 行空け) 推奨
- 一人称固定（「私」「制作してて」等）。三人称・カタログ口調は禁止
- 絵文字は 1 文に最大 1 個
- 表記ルール (時刻 24h / 運用メモ AM/PM) は `day-of-reminder` と共通

### 変数解決ロジック (`behind-the-scenes` / `next-teaser` 共通)

resolver は **コレクション `workflow-state.json` + channel-config** から段階的に解決:

1. `planning.scene_phrase` / `planning.target_persona` / `planning.signature_objects` を Read
2. 不足分は `config/channel/community-draft.json::shared_variables` から
3. それでも不足なら `config/channel/content.json::genre` から派生 (`music_style` のみ)
4. すべて欠落なら placeholder を残したまま draft 出力し、警告ログ

`scene_phrase` / `animal_object` / `drink_signature` / `music_style` の 4 変数は本 skill が公式に提供する render 変数（issue #509）。

## `next-teaser` の構造（#509 で upstream 化）

次コレクションを「公開時期は曖昧に保ったまま」匂わせる短文投稿。
`config.default.yaml::templates.next_teaser` の構造順:

1. **continuity_bridge** — 1 文: 直近公開コレクションへの感謝 or 余韻
2. **next_hook** — 1 文: 次コレクションの `scene_phrase` を **匂わせる** 程度に提示
   - 「来週公開」のような具体日付は出さない (Studio 予約が確定するまで曖昧表現)
3. **invite_to_vote** — 1 文 (optional): `weekly-feedback` がアクティブなら投票 CTA を絡める

### 次コレクション `workflow-state.json` 参照ロジック

`next-teaser` は **次に公開予定のコレクション** の workflow-state を参照する:

1. `collections/planning/` 配下から `workflow-state.json::planning.publish_target_at` を持つものを列挙
2. 未確定 (`publish_target_at == null`) は除外
3. 最も近い未来日 (`publish_target_at` が今より後で最小) のコレクションを採用
4. 候補ゼロのときは `content.json::genre.label` から汎用 hook を生成 (`Next is brewing —`)

採用後、そのコレクションの `planning.scene_phrase` を `next_hook` の主軸に据える。
**Publishing 確定前** (`workflow-state.json::publish.scheduled_at` が未設定) は
時刻表記（24h / AM/PM のいずれも）を出さない。「Coming soon」「Brewing now」など曖昧表現を使う。

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
2. `load_skill_config("community-draft")` 相当の順序で `.claude/skills/community-draft/config.default.yaml` と任意の `config/skills/community-draft.yaml` を deep-merge し、該当 type の skill-config ブロックを基準にする
   - その後、既存手順どおり `config/channel/community-draft.json` を読み、チャンネル固有のテンプレ上書き・`shared_variables`・軸定義を適用する
   - merge 優先順は `config.default.yaml` < `config/skills/community-draft.yaml` < `config/channel/community-draft.json`
3. テンプレ変数を解決
   - `behind-the-scenes` / `next-teaser`: コレクション `workflow-state.json` の `planning.*` + channel-config の `shared_variables` から `scene_phrase` / `animal_object` / `drink_signature` / `music_style` を resolve
   - `day-of-reminder`: コレクション `workflow-state.json` から公開日時 / scene_phrase / drink 等を引く
   - `weekly-feedback`: `data/community/weekly-vote-log.json`（存在すれば）の直近履歴 (`utils.weekly_vote_log.load_weekly_vote_log()` 経由) から提示 N-1 択を選定
   - `poll`: 後方互換のみ受理し `utils.weekly_vote_log.warn_poll_deprecated()` で warning ログを残す
4. 本文を生成し `30-promo/community-post-draft.md` または `branding/community-templates/<type>.md` に保存
5. `pbcopy` でクリップボードへ送り、Studio を `open` で開く案内を出す

## 配布されるサンプル

`examples/community-draft-rjn/` に rjn 実例を **reference のみ** として収録（デフォルト config には反映されない）:

- `rain-5-axis.yaml` — rjn の 5 軸 axis_pool 構造
- `day-of-reminder-cloudwalk.md` — 当日リマインダー本文例

ダウンストリームが「真似て自分のチャンネル軸に書き換える」ためのテンプレ。

## vote-log との連携（#509 で正式化）

`weekly-feedback` で集計した投票結果は `data/community/weekly-vote-log.json` に
**週次で append** する。スキーマは `youtube_automation.utils.schemas.weekly_vote_log.schema.json` 参照。

```bash
# CLI から append (channel リポジトリで実行)
uv run yt-vote-log append \
  --week-start 2026-05-04 \
  --axis rain_window:Rain Window:124 \
  --axis midnight_drive:Midnight Drive:98

# 直近 4 週の weight + forced_axis を表示 (collection-ideate hook と同一ロジック)
uv run yt-vote-log weights --recent 4 --decay 0.7

# schema 検証 (CI 用)
uv run yt-vote-log validate
```

Python から append したい場合は `youtube_automation.utils.weekly_vote_log.append_weekly_vote_entry()` を直接呼び出す（loader / writer / validator はすべて同モジュールに集約）。

下流の `/collection-ideate` は `compute_vote_log_weights(log, recent_weeks=4)` を hook として呼び、

- **連続 2 週 1 位の軸** → `forced_axis` として返り、theme weight を最大化（強制採用）
- それ以外 → 軸ごとの **重みづけ平均** (`decay^i` を最新ほど高く) を `weights` で加点

する。詳細は `/collection-ideate` SKILL.md の「vote-log hook」セクションを参照。

## スコープ外

- vote の自動集計（YouTube コミュニティ投稿の poll 結果は Studio から手動で `yt-vote-log append` する運用）
- コミュニティ投稿の自動投稿（YouTube Data API v3 非対応のため Studio から手動）

## 参考

- issue #309（本スキル新設）
- issue #509（既存 type フル仕様化 + vote-log hook 正式化、本 PR）
- vote-log API: `youtube_automation.utils.weekly_vote_log`
- JSON Schema: `youtube_automation.utils.schemas.weekly_vote_log.schema.json`
- CLI: `yt-vote-log {append, show, weights, validate}`
- rjn 実装: `config/channel/community-draft.json` / `branding/community-templates/weekly-feedback.md` / `collections/live/20260515-rjn-cloudwalk-collection/30-promo/community-post-draft.md`
- 流派: jazzgak. TTP（韓国系 lo-fi jazz × 雨音、ER 平均 2.68%）
