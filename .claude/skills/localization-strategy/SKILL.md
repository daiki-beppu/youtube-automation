---
name: localization-strategy
description: Use when `config/localizations.json` の `supported_languages` を広告単価 (CPM) ベースで見直したいとき。`yt-localization-roi` で過去 90 日の国別 views と公開参考 CPM から言語別 ROI を推定し、追加・維持・削除候補を Markdown レポートで提示する。「ローカライズ戦略見直し」「en/de を追加すべき？」「ko / zh-CN を残すべき？」「supported_languages を絞り込みたい」など、多言語展開の費用対効果判断が必要な場面で発動する。
---

## Overview

各下流チャンネルの `config/localizations.json` の `supported_languages` を、広告単価 (CPM) と実視聴シェアの掛け合わせで再評価するためのワークフロー。

`yt-localization-roi` CLI は YouTube Analytics の国別 views と、公開されている国別 CPM 参考テーブル (`utils/localization_strategy.py`) を組み合わせて、**言語別の推定収益** を算出する。結果を Markdown レポートで出力し、追加・維持・削除候補を明示する。

**重要**: 出力される推定収益は公開 CPM × views の単純積算であり、実 AdSense 値とは乖離する。判断補助の参考値として扱うこと。

## 前提

- `config/channel/` が存在する (`load_config()` でロードできる)
- `auth/token.json` で YouTube Analytics API にアクセスできる
- 過去 90 日に視聴データが蓄積されていること (新規チャンネルは判定不能)

満たさない場合の案内:
- 設定なし → `/channel-new` または `/channel-import`
- 認証不備 → `/onboard` でトークン再発行

## When to Use

- 既存 `supported_languages` の費用対効果を再評価したいとき
- 高 CPM 言語 (en / de) の追加検討
- 低 CPM 言語 (ko / zh-CN 等) の削除検討
- 翻訳メンテコストと収益貢献のバランスを取りたいとき

逆に使わない場面:
- 単一動画のサムネ・タイトル A/B テスト → `/analytics-analyze`
- 視聴維持率の改善 → `/analytics-analyze`

## Quick Reference

| 引数 | 説明 | デフォルト |
|---|---|---|
| `--days <N>` | 集計期間の日数 | 90 |
| `--max-countries <N>` | Top N 国まで集計 | 30 |
| `--output <path>` | Markdown 出力先 | `<channel_dir>/data/localization_roi/<YYYY-MM-DD>.md` |
| `--json` | stdout に構造化 JSON のみ | (default) |
| `--text` | stdout に人間向け要約 | — |
| `--keep-floor <N>` | 維持判定の view_share % 下限 | 0.5 |
| `--add-floor <N>` | 追加判定の view_share % 下限 | 1.0 |

## Workflow

1. **データ収集**:
   ```bash
   uv run yt-localization-roi --days 90 --text
   ```
   `<channel_dir>/data/localization_roi/<YYYY-MM-DD>.md` に詳細レポート、stdout に要約が出る。

2. **レポート確認**: 出力 Markdown の以下セクションを順に確認
   - 国別 views: 上位国の主要言語が現状 `supported_languages` と整合しているか
   - 言語別集計: 推定収益降順で言語の優先度を把握
   - 推奨 supported_languages: `Add` / `Keep` / `Consider removing` の 3 区分

3. **人間判断**: レポートはあくまで参考値。最終判断軸:
   - **CPM 信頼性**: 同言語でも国別 CPM 差が大きい (ES vs MX で 10x、PT vs BR で 6x)。`top_countries` を必ず確認
   - **翻訳メンテコスト**: 言語数 × コレクション数で線形増。実用上限は 3〜5 言語
   - **戦略的位置付け**: ja はベース言語として維持、en は最高 CPM 帯で追加優先

4. **`localizations.json` 編集** (この skill では行わない):
   - 編集は **各下流チャンネルリポジトリの PR** で行う
   - 編集後に `metadata_generator` が全 `supported_languages` で翻訳を回す前提を満たすか確認

## 注意事項

- 推定値であり、実 AdSense 値ではない。SKILL 案内文・レポート末尾にも明記済み
- `utils/localization_strategy.py::COUNTRY_CPM_USD` は **半年ごとに見直し**。参考出典は `references/cpm-sources.md`
- 未マッピング国は `other` バケットに集約され、推奨対象から除外される
- 過去 90 日に視聴のない言語は `判定保留` として `keep` に残る

## 関連

- `utils/localization_strategy.py` — マッピング・参考 CPM テーブル
- `utils/audience_analytics.py::get_country_analytics` — 国別 views 取得
- `utils/config/localizations.py` — `Localizations` dataclass
- Issue #272 — ローカライズ戦略見直し
