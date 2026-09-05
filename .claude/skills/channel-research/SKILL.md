---
name: channel-research
purpose: 調べる
description: "Use when チャンネル調査を状態判定付きで一括実行または一段だけ実行するとき。競合データ収集は --benchmark、追加競合候補の発掘は --discover、TTP・ニッチ仮説の比較または収集済みデータ分析は --market、競合コメントからの視聴者インサイト抽出は --voice、競合サムネイルの上位群・下位群比較は --thumbnail を使う。「競合データ収集」「ベンチマーク更新」「競合候補」「競合発掘」「市場調査」「競合分析」「チャンネルリサーチ」「TTP 対象抽出」「視聴者の声」「コメント分析」「ユーザーリサーチ」「サムネイル徹底分析」「競合サムネ分析」「サムネ勝ちパターン」で発動。方向性の決定は channel-strategy の direction mode、サムネイル生成は /thumbnail を使う"
---

## 前後工程

- `前工程`: `/setup --channel`, `/setup --import`
- `後工程`: `/channel-strategy --direction`, `/channel-strategy --persona`, `/wf-new`, `/thumbnail`
- `委譲先`: `なし`

## 成果物

- `書き込む`: `docs/benchmarks/benchmark-report.json`, `docs/benchmarks/benchmark-report.html`, `docs/benchmarks/thumbnails/<channel>_<video-id>.jpg`, `data/benchmark_<YYYYMMDD>.json`, `research/<niche>-discovery.md`, `research/<niche>-discovery.csv`, `.cache/youtube-automation/discover-competitors-search.json`, `docs/research/market-<YYYY-MM-DD>.json`, `docs/research/market-<YYYY-MM-DD>.html`, `docs/channel-research.json`, `docs/channel-research.html`, `data/comments_<YYYYMMDD>.json`, `docs/plans/viewer-voice-analysis.json`, `docs/plans/viewer-voice-analysis.html`, `docs/benchmarks/thumbnail-analysis.json`, `docs/benchmarks/thumbnail-analysis.html`, `data/thumbnail_compare/benchmark/*_<video-id>.jpg`
- `読み込む`: `config/channel/analytics.json`, `config/channel/content.json`, `config/skills/benchmark.yaml`, `config/skills/discover-competitors.yaml`, `data/benchmark_*.json`, `data/comments_*.json`, 検証済み channel-research report JSON, `data/video_analysis/<channel>/<video-id>.json`

## モード判定

`$ARGUMENTS` から、下表に登録された mode flag の個数を最初に数える。同じ flag の重複も別々に数える。

- 2 個以上なら排他違反として停止し、1 つだけ指定するよう促す
- 1 個なら対応する reference を読み、その一段だけを実行する。残りの引数はその mode の引数として扱う
- 0 個なら chain manifest に従い状態判定付きで進める
- mode は上限 5 件であり、下表の 5 mode 以外は未知の mode として停止する。判定規則を複製しない

| mode | 読む reference |
|---|---|
| `--benchmark` | `references/benchmark.md` |
| `--discover` | `references/discover.md` |
| `--market` | `references/market.md` |
| `--voice` | `references/voice.md` |
| `--thumbnail` | `references/thumbnail.md` |

## 共通前提

分析レポートの保存・移行・読み取りは `references/structured-report.md` を正本とする。AI と下流 skill は JSON+HTML pair を検証し、JSON だけを入力に使う。

`config/channel/` が存在し、`load_config()` でロード可能であること。満たさない場合は、新規チャンネルなら `/setup --channel`（`.claude/skills/setup/references/ttp-seed-and-duration.md`）、既存チャンネルなら `/setup --import` を案内して停止する。

## 設定読み込みゲート

同梱 default は mode ごとの `benchmark` / `discover` 節に分ける。公開 skill 名の統合後も Python と下流 override の設定キーは互換性のため `benchmark` / `discover-competitors` のまま維持する。

| mode | 同梱 default | チャンネル上書き | loader |
|---|---|---|---|
| `--benchmark` | `.claude/skills/channel-research/config.default.yaml::benchmark` | `config/skills/benchmark.yaml`（存在する場合） | `load_skill_config("benchmark")` |
| `--discover` | `.claude/skills/channel-research/config.default.yaml::discover` | `config/skills/discover-competitors.yaml`（存在する場合） | `load_skill_config("discover-competitors")` |

各行の default とチャンネル上書きを deep-merge し、上書きを優先する。`config/skills/channel-research.yaml` は先行作成しない。名前空間キーへの実移行が提供された段階で `uv run yt-skills migrate-config --channel-dir . --dry-run` で計画を確認し、明示 apply する。現段では旧キーを改名せず、下流 override を勝手に作成しない・変更しない。

`--market` の旧 2 owner、`--voice` と `--thumbnail` の旧 owner は `config.default.yaml` / `config/skills/*.yaml` を持たなかったため、新しい設定キーや override を先行作成しない。

## 一括実行

`references/channel-research-chain-manifest.json` と `references/channel-research-chain-state.py` を検証し、manifest 順に `benchmark` → `discover` → `voice` → `market` を進める。`voice` を `market` より先に置くことで、collected-analysis branch が必要とするコメント成果物を同じ chain 内で準備する。

`--thumbnail` は任意の深掘りであり chain manifest には含めない。フラグなし実行では起動せず、明示指定された場合だけ `references/thumbnail.md` を読む。

```bash
uv run python .claude/skills/channel-research/references/channel-research-chain-state.py \
  --channel-dir . --step <benchmark|discover|voice|market>
```

| exit | `decision` | 処理 |
|---:|---|---|
| 0 | `skip` | その段の成果物条件を満たしているため記録し、manifest の次の段の状態判定へ進む |
| 10 | `run` | 判定した `step` に `--` を付けてモード表の reference を引き、その段だけを実行する（例: `voice` → `--voice` → `references/voice.md`） |
| 20 | `blocked` | 不足している前提と解消方法を表示して停止する |
| その他 | `error` | config / manifest / script のエラーとして停止する |

実行後は同じ `step` の状態判定を再実行し、exit 0 になった段だけ次へ進む。`run` のままなら成果物が未完了、`blocked` / `error` なら理由を示してその段で止める。先頭や途中の `skip` で chain 全体を終了しない。再発動時は manifest の先頭から状態を確認し、完了済みの段を飛ばして未完了の段へ進む。

## 完了条件

- フラグなし: manifest の四工程 `benchmark`、`discover`、`voice`、`market` がすべて `skip` または実行後 `skip` になっている。全段が最初から `skip` なら収集・分析を再実行せず完了する
- `--benchmark`: `references/benchmark.md` の完了条件を満たしている
- `--discover`: `references/discover.md` の完了条件を満たしている
- `--market`: `references/market.md` が自動選択した branch の完了条件を満たしている
- `--voice`: `references/voice.md` の完了条件を満たしている
- `--thumbnail`: `references/thumbnail.md` の完了条件を満たしている

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
| YouTube Data API v3 commentThreads.list | `--voice` の対象動画数 × 1 call | 1 万再生以上の動画数、`--min-views`、`--max-comments` |
| 外部 API | `--thumbnail` は 0 call | 既存のローカル benchmark JSON・画像・分析だけを使用 |

- 上限 / 承認: `freshness_days` 内は skip し、収集実行は `-y` / `--force` がない限り事前確認する
