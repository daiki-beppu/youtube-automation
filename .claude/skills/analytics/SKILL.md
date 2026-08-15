---
name: analytics
description: "Use when YouTube Analytics の収集・分析・レポート表示を一括実行または一段だけ実行するとき。フラグなしは収集→分析→表示を状態判定付きで進める。「Analytics 一括実行」「データ更新」「パフォーマンス分析」「レポート見せて」で発動。一段だけは排他的な --collect / --analyze / --report を使う"
---

## 前後工程

- `前工程`: `/setup`
- `後工程`: `/collection-ideate`, `/flop-analysis`
- `委譲先`: `なし`

## モード判定

`$ARGUMENTS` から `--collect` / `--analyze` / `--report` の個数を最初に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い collect → analyze → report を状態判定付きで進める

| mode | 読む reference |
|---|---|
| `--collect` | `references/collect.md` |
| `--analyze` | `references/analyze.md` |
| `--report` | `references/report.md` |

## 共通前提

`config/channel/` が存在し、`load_config()` でロード可能であること。満たさない場合はここで停止する。

- **新規チャンネル（config 未作成）** → `/setup --channel` を案内して停止する
- **既存チャンネル（load_config() 失敗）** → `/channel-new`（既存チャンネル取り込みモード）を案内して停止する

## 設定読み込みゲート

skill-config は次を deep-merge する。

1. `.claude/skills/analytics/config.default.yaml`
2. `config/skills/analytics.yaml`（存在する場合）

合成規則は `youtube_automation.configuration.skills.load_skill_config("analytics")` と同じで、チャンネル上書きを優先する。存在しない override は勝手に作成しない。

## 一括実行

`references/analytics-chain-manifest.json` と `references/analytics-chain-state.py` が存在し、manifest の `chainId`、step 順、step mode、approval gate、状態判定 script が妥当であることを確認する。欠損、未知・重複 step、複数 mode、`approvalGate.skip != true` があれば停止する。旧 `enabled` だけの gate は `skip = not enabled` として解決し、`skip` と `enabled` の同時指定は拒否する。

チャンネルルートで manifest 順に次を実行する。

```bash
uv run python .claude/skills/analytics/references/analytics-chain-state.py \
  --channel-dir . --step <collect|analyze|report>
```

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | 完了済みとして次段へ進む |
| 10 | `run` | step の mode reference を読み、その一段を実行する |
| 20 | `blocked` | `reason` と不足・古い成果物を提示して停止する |
| その他 | `error` | config / manifest / script のエラーとして停止する |

実行後は同じ状態判定を再実行し、collect / analyze が exit 0 にならなければ停止する。report は表示を永続化しないため exit 10 が正常であり、`references/report.md` の latest 表示を行う。途中失敗時はその段で止め、再発動時は先頭から状態判定して完了済み段を skip する。

## 完了条件

- フラグなし: collect と analyze が `skip` または実行後 `skip`、report が `run` となり、最新 Markdown を表示している
- mode 指定: 対応する reference の完了条件だけを満たし、他の mode を実行していない

実行段、skip 段、`freshness_minutes` と `freshness_source`、成果物または表示したレポートを短く報告する。

## 想定 API call 数

`--report` はローカル成果物だけを読む。`--analyze` は VPD ranking のため YouTube Data API を 1 回の走査で使う。フラグなしまたは `--collect` で収集が必要な場合は collect 分も加えて次の call 数を見込む。

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data API v3 | 約 3 + ceil(動画数/50) units | チャンネルの動画数 |
| YouTube Data API v3（analyze VPD） | 約 3 + 2 × ceil(動画数/50) units | uploads 全ページ + statistics 50 件 batch。鮮度内 schema v3 レポートは再利用 |
| YouTube Analytics API | standard で約 10 + 直近動画数 call | 対象期間、動画数 |
| YouTube Analytics API（full 追加分） | country / retention で最大 +11 call | full 指定時のみ |
| YouTube Reporting API | reporting mode 時のみ数 call | job と生成済み report の状態 |

鮮度内の既存データは再利用する。standard 収集の実行コマンドは `uv run yt-analytics`。その他の mode と詳細な上限は `references/collect.md` を正とする。

- 上限 / 承認: `freshness_minutes` 内の成果物があれば収集を skip し、Reporting job 作成前は dry-run で状態を確認する

## dashboard との境界

`yt-dashboard` は chain を起動せず、registry の全チャンネルへ `--collect` 相当の standard 収集だけを直列実行する。API call 数と `--skip-refresh` の例外は `references/collect.md` を正とする。
