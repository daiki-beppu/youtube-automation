# Analytics report mode

## Overview

`reports/analysis_*.json` を検証し、同 basename の自己完結 HTML を表示する。JSON が唯一の AI 入力で、HTML は共通 renderer による human view とする。

## 完了条件

- `latest` / 引数なし: ファイル名日付が最新の JSON+HTML pair を検証し、HTML を表示した時点
- `html`: 最新 JSON を `analysis-report.schema.json` で検証して共通 renderer から HTML を再生成し、再読込後に表示した時点
- `list`: 検証済み JSON+HTML pair の一覧を表示した時点

不正 JSON、schema 違反、HTML 欠損、JSON と対応しない stale HTML は成功扱いにしない。Markdown は表示にも AI 入力にも使用しない。

## 前提

`config/channel/` が存在し `load_config()` でロード可能であること。満たさない場合は次を案内して停止する。

- **新規チャンネル** → `/setup --channel` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内

## Quick Reference

| 引数 | 説明 |
|---|---|
| `/analytics --report latest` | 最新の検証済み分析レポートを表示 |
| `/analytics --report html` | 最新 JSON から同 basename HTML を原子的に再生成 |
| `/analytics --report list` | 検証済み report pair の一覧 |
| `/analytics --report` | `latest` と同じ |

## Instructions

最新判定は更新時刻ではなく `analysis_YYYYMMDD.json` のファイル名日付で行う。同日付 `.html` が存在する候補だけを列挙し、`analysis-report.schema.json` による JSON validation と、共通 renderer が生成する HTML との完全一致を確認する。`latest` と `list` はローカルファイルを変更しない。

`html` は次だけを実行する。個別 CSS、Chart.js/CDN、別名 dashboard HTML、Markdown 由来の入力を作らない。

```bash
uv run yt-document-render reports/analysis_YYYYMMDD.json \
  --schema analysis-report.schema.json
```

CLI が exit 0 でも JSON と HTML を再読込し、schema validation と対応関係が成功した場合だけ表示する。既存 HTML は temp write + fsync + replace の共通 atomic contract により、失敗時に保持される。

## 表示順

schema の `x-view` を正本とし、入力/根拠 → 主要指標 → VPD/勝ち型比較 → retention/収益 → 戦略的示唆 → 次期候補 → 推奨 action → 戦略ディスカッションの認知順で表示する。dashboard機能や KPI 定義は追加しない。
