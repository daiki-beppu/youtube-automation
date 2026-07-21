---
name: analytics-run
description: "Use when YouTube Analytics の収集→分析→最新レポート表示を 1 回で完了・再開したいとき。「Analytics 一括実行」「データ更新からレポートまで」「analytics run」で発動。収集・分析・表示の一段だけを実行する場合は /analytics-collect、/analytics-analyze、/analytics-report を使う"
---

## 前後工程

- `前工程`: `/setup`
- `後工程`: `/collection-ideate`, `/flop-analysis`

## Hard Gates

- `config/channel/` が存在し、`load_config()` でロード可能であること。満たさない場合は `/channel-new` を案内して停止する。
- `references/analytics-chain-manifest.json` と `references/analytics-chain-state.py` が存在すること。欠損、JSON 構文エラー、未知の step、重複 step ID があれば停止する。
- manifest の順序を変更せず、1 回の発動で `collect` → `analyze` → `report` を最後まで進める。途中失敗時だけ停止する。
- 子 skill の内部手順を再実装しない。各段では対応する SKILL.md を読み、その完了条件をそのまま満たす。
- このチェーンは外部反映を行わないため承認を求めない。manifest の全 `approvalGate.skip` が `true` でなければ設定エラーとして停止する。旧 `enabled` だけの manifest は `skip = not enabled` として解決し、`skip` と `enabled` の同時指定は拒否する。

## 完了条件

状態判定が `collect` と `analyze` を `skip` または実行後 `skip`、`report` を `run` と判定し、`/analytics-report latest` が最新 Markdown を表示した時点で完了する。各判定の JSON（step、decision、reason、閾値、設定元、成果物）を要約して提示する。

## 状態判定契約

チャンネルルートで次を実行する。`freshness_minutes` は `.claude/skills/analytics-collect/config.default.yaml` の既定値を使い、対象チャンネルの `config/skills/analytics-collect.yaml` があれば deep-merge した上書き値を使う。

```bash
uv run python .claude/skills/analytics-run/references/analytics-chain-state.py \
  --channel-dir . --step <collect|analyze|report>
```

exit code は次の固定契約とする。

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | 完了済み。子 skill を実行せず次段へ進む |
| 10 | `run` | 対応する子 skill を実行する |
| 20 | `blocked` | `reason` と不足・古い成果物を提示して停止する |
| その他 | `error` | config / manifest / script のエラーとして停止する |

判定ロジックを本文で再実装・推測しない。JSON stdout と exit code の両方を使う。

## 実行手順

1. `references/analytics-chain-manifest.json` を読み、`chainId == "analytics"`、step 順が `collect, analyze, report`、全 `approvalGate.skip` が `true`、全 step が同じ状態判定 script を参照していることを確認する。
2. manifest 順に各 step の状態判定を実行する。
3. `collect` が exit 10 なら `/analytics-collect` を実行する。完了後に状態判定を再実行し、exit 0 にならなければ停止する。
4. `analyze` が exit 10 なら `/analytics-analyze` を実行する。完了後に状態判定を再実行し、exit 0 にならなければ停止する。
5. `report` が exit 10 なら `/analytics-report latest` を実行する。表示は永続成果物を作らないため、再発動時も常に実行する。
6. 実行段、skip 段、使用した `freshness_minutes` と `freshness_source`、表示したレポートを短く報告する。

途中で失敗した場合はその段で停止する。再発動時は状態判定を先頭からやり直し、鮮度を満たす完了済み段を exit 0 で skip して未完了段から再開する。

## dashboard との境界

`yt-dashboard` はこのチェーンを起動せず、registry の全チャンネルへ `/analytics-collect` 相当の standard 収集だけを直列実行する。API call 数は登録チャンネル数に比例し、分析・Markdown report 表示は行わない。詳細な見積もりと `--skip-refresh` の例外は `/analytics-collect` の「想定 API call 数」を正とする。

## References

- `references/analytics-chain-manifest.json`: step 順、成果物、gate、判定 script の単一ソース
- `references/analytics-chain-state.py`: 成果物タイムスタンプ、依存関係、設定値を評価する単一ソース
