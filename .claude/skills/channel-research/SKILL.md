---
name: channel-research
purpose: 調べる
description: "Use when チャンネル調査を状態判定付きで一括実行または一段だけ実行するとき。競合データ収集は --benchmark、追加競合候補の発掘は --discover、TTP・ニッチ仮説の比較または収集済みデータ分析は --market を使う。「競合データ収集」「ベンチマーク更新」「競合候補」「競合発掘」「市場調査」「競合分析」「チャンネルリサーチ」「TTP 対象抽出」で発動。方向性の決定は /channel-new を使う"
---

## 前後工程

- `前工程`: `/setup --channel`, `/setup --import`
- `後工程`: `/channel-new`, `/viewer-voice`, `/wf-new`, `/thumbnail-research`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `docs/benchmarks/<channel>.md`, `docs/benchmarks/thumbnails/<channel>_<video-id>.jpg`, `data/benchmark_<YYYYMMDD>.json`, `research/<niche>-discovery.md`, `research/<niche>-discovery.csv`, `.cache/youtube-automation/discover-competitors-search.json`, `docs/research/market-<YYYY-MM-DD>.md`, `docs/channel-research.md`, `docs/benchmarks/thumbnail-text-profile.md`
- `読み込む`: `config/channel/analytics.json`, `config/channel/content.json`, `config/skills/benchmark.yaml`, `config/skills/discover-competitors.yaml`, `data/benchmark_*.json`, `data/comments_*.json`, `docs/benchmarks/*.md`

## モード判定

`$ARGUMENTS` から、下表に登録された mode flag の個数を最初に数える。同じ flag の重複も別々に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い状態判定付きで進める
- `--voice` / `--thumbnail` は後続段で登録する予約名であり、現段では未知の mode として停止する。mode はこの表へ最大 5 件まで追加でき、判定規則を複製しない

| mode | 読む reference |
|---|---|
| `--benchmark` | `references/benchmark.md` |
| `--discover` | `references/discover.md` |
| `--market` | `references/market.md` |

## 共通前提

`config/channel/` が存在し、`load_config()` でロード可能であること。満たさない場合は、新規チャンネルなら `/setup --channel`（`.claude/skills/setup/references/ttp-seed-and-duration.md`）、既存チャンネルなら `/setup --import` を案内して停止する。

## 設定読み込みゲート

同梱 default は mode ごとの `benchmark` / `discover` 節に分ける。公開 skill 名の統合後も Python と下流 override の設定キーは互換性のため `benchmark` / `discover-competitors` のまま維持する。

| mode | 同梱 default | チャンネル上書き | loader |
|---|---|---|---|
| `--benchmark` | `.claude/skills/channel-research/config.default.yaml::benchmark` | `config/skills/benchmark.yaml`（存在する場合） | `load_skill_config("benchmark")` |
| `--discover` | `.claude/skills/channel-research/config.default.yaml::discover` | `config/skills/discover-competitors.yaml`（存在する場合） | `load_skill_config("discover-competitors")` |

各行の default とチャンネル上書きを deep-merge し、上書きを優先する。`config/skills/channel-research.yaml` は先行作成しない。名前空間キーへの実移行が提供された段階で `uv run yt-skills migrate-config --channel-dir . --dry-run` で計画を確認し、明示 apply する。現段では旧キーを改名せず、下流 override を勝手に作成しない・変更しない。

`--market` の旧 2 owner は `config.default.yaml` / `config/skills/*.yaml` を持たなかったため、新しい設定キーや override を先行作成しない。

## 一括実行

`references/channel-research-chain-manifest.json` と `references/channel-research-chain-state.py` を検証し、manifest 順に `benchmark` → `discover` → `market` を進める。

```bash
uv run python .claude/skills/channel-research/references/channel-research-chain-state.py \
  --channel-dir . --step <benchmark|discover|market>
```

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | 鮮度内の成果物が揃っているため完了として終了する |
| 10 | `run` | `references/benchmark.md` を読み、同じ一段を実行する |
| 20 | `blocked` | 不足している前提と解消方法を表示して停止する |
| その他 | `error` | config / manifest / script のエラーとして停止する |

実行後は状態判定を再実行し、exit 0 にならなければ完了扱いにしない。途中失敗時はその段で止め、再発動時は同じ判定から安全に再開する。

## 完了条件

- フラグなし: `benchmark`、`discover`、`market` が `skip` または実行後 `skip` になっている
- `--benchmark`: `references/benchmark.md` の完了条件を満たしている
- `--discover`: `references/discover.md` の完了条件を満たしている
- `--market`: `references/market.md` が自動選択した branch の完了条件を満たしている

実行段、skip 段、使用した `freshness_days` と設定 source、更新成果物を短く報告する。

## 想定 API call 数

各 mode の詳細は対応 reference を正とする。

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| YouTube Data API v3 | `ceil(更新チャンネル数 / 50) + 更新チャンネル数 × 2 × ceil(scan_recent / 50)` units | 更新チャンネル数、`scan_recent` |
| Vertex AI Gemini | 既定 OFF。有効時は分析対象サムネイル枚数分 | `gemini_thumbnail_analysis`、対象枚数 |
| YouTube Data API v3 search.list | `--discover` のキーワード数 × 100 units | キーワード数（既定 3-5、上限 8） |
| YouTube Data API v3 channels.list / videos.list | `--discover` の候補数に応じて約 1 + 2 × 候補数 units | pre-filter 通過数 |
| Web 検索 / 接続済み一次情報 | `--market` の `market-comparison` branch で根拠数に応じる | 比較対象数、評価軸数。`collected-analysis` は 0 call |

- 上限 / 承認: `freshness_days` 内は skip し、収集実行は `-y` / `--force` がない限り事前確認する
