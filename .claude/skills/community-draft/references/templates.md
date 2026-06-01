# community-draft テンプレ参照メモ

`community-draft` skill が生成する本文テンプレの詳細メモ。
各 type の構造は `SKILL.md` 本文と `config.default.yaml` に集約してあり、ここではダウンストリームが
実装する際に陥りやすい注意点だけ補足する。

## 表記ルールの分離（必読）

issue #309 で確定した **2 表記分離** ルール:

| 用途 | 表記 | 変数名 | 例 |
|---|---|---|---|
| 投稿本文の時刻 | **24h** | `{publish_time_24h_primary}` / `{publish_time_24h_secondary}` | `18:00 EDT / 07:00 JST` |
| 運用メモ・予約時刻 | **AM/PM** | `{schedule_window_local_ampm}` / `{schedule_time_ampm}` | `6:00 PM EDT` |

skill 実装で 2 表記が混ざると視聴者向け簡潔さ（24h）と Studio UI 整合（AM/PM）の両立が崩れるので、
**生成時点で別変数として扱う** こと。

## 装飾フォント（Mathematical Bold sans-serif）

`decorative_font: true` のとき、見出しと署名を Unicode の数式文字に変換する想定。

- 例: `New drop today` → `𝐍𝐞𝐰 𝐝𝐫𝐨𝐩 𝐭𝐨𝐝𝐚𝐲`
- 注意: YouTube Studio のテキストエディタで一部欠ける可能性あり。プレビューで欠けていたら
  生成 md からコピペし直すか、`decorative_font: false` で再生成する運用フォールバックを案内する

## `day-of-reminder` のオフセット

公開時刻の何時間前に投稿するかは **チャンネルの投稿運用リズム** に依存する:

- rjn: 公開 12h 前固定（毎日投稿の場合、視聴者の期待リズムを定着させるため）
- 週 1 投稿チャンネル: 公開 2-6h 前で十分

upstream デフォルトでは強制せず、ダウンストリーム側で `config/channel/community-draft.json` 経由で
`offset_hours` 等を持たせる想定（フル仕様化は follow-up）。

## `weekly-feedback` のローテ規則

`rotation_rule.present_count: "auto"` の場合の挙動:

- `axis_count - 1` 択を毎週提示
- 各週 1 軸ずつ除外して回す → `axis_count` 週で 1 周
- 例: 5 軸 → 4 択 × 5 週 1 周

`vote_log_path`（`data/community/weekly-vote-log.json`）の正式スキーマと
`/collection-ideate` への hook 実装は **#509** で完了。スキーマは
`youtube_automation.utils.schemas.weekly_vote_log.schema.json`、
loader / append / hook は `youtube_automation.utils.weekly_vote_log` モジュール。
CLI は `yt-vote-log {append, show, weights, validate}`。

## 投稿頻度の上限ガイド

YouTube コミュニティ投稿は週 2-3 本が推奨上限（多すぎると視聴者ホーム画面でうるさい）。

- 毎日投稿チャンネル: 公開当日リマインダー + 日曜 vote の **週 2 本運用**
- 週 1 投稿チャンネル: 公開当日リマインダーのみ or 隔週で次予告

これは skill 側で強制せず、ユーザーへの注意として SKILL.md に記載するに留める。

## 関連

- issue #309: 本スキル新設
- rjn 実装: `branding/community-templates/weekly-feedback.md`
- TTP 元: jazzgak.（韓国系 lo-fi jazz × 雨音、ER 平均 2.68%）
