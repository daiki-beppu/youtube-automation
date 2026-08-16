# Structured report contract

channel-research の分析レポートは `channel-research-report.schema.json` に適合する JSON を唯一の正本とし、同 basename の HTML を表示用成果物とする。`data/benchmark_*.json` と `data/comments_*.json` は API 収集の生データであり、分析レポートの正本ではない。

| mode | report_type | 公開先 |
|---|---|---|
| `--benchmark` | `benchmark` | `docs/benchmarks/benchmark-report.json` + `.html` |
| `--market` | `market` | comparison: `docs/research/market-<YYYY-MM-DD>.json` + `.html`; collected: `docs/channel-research.json` + `.html` |
| `--voice` | `viewer_voice` | `docs/plans/viewer-voice-analysis.json` + `.html` |
| `--thumbnail` | `thumbnail` | `docs/benchmarks/thumbnail-analysis.json` + `.html` |

JSON には `generated_at`、任意の `collection_id`、入力 path・確認日時・対応する主張を持つ `source_provenance`、`competitor_comparison`、`winning_patterns`、ID で追跡できる `evidence`、`application_candidates` を保存する。比較・主張は必ず `evidence_ids` で根拠へ接続する。

## 保存

subagent は未公開 candidate を一時 directory に作り、次の共通 workflow だけで公開する。公開先と同 basename の Markdown が存在する場合は、内容を candidate JSON へ移した後、ユーザーの明示 yes/no を得る。yes のときだけ `--migration-decision yes`、no のときは `--migration-decision no` を渡す。Markdown が無い新規作成・移行済み更新ではこの option を渡さない。

```bash
uv run yt-document-migrate "$candidate" \
  --target docs/benchmarks/benchmark-report.json \
  --schema channel-research-report.schema.json
```

共通 workflow は JSON と HTML を一つの原子的 operation として公開し、両方の再読込・schema 検証・対応確認に成功した後だけ Markdown を削除する。pair 不整合、検証失敗、書込失敗では既存成果物を保持して停止する。JSON または HTML の片方だけを手書き更新しない。

## 読み取り

AI と下流 skill は Markdown や HTML を分析入力にせず、`read_published_json_document(path, RepositorySchema.CHANNEL_RESEARCH_REPORT)` が返す検証済み JSON だけを読む。pair 欠落・schema 不適合・HTML 不一致は前工程へ戻して停止する。HTML は人が比較表、勝ちパターン、根拠、適用候補を確認する表示専用成果物である。
