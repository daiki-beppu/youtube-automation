# マルチチャンネル dashboard: 2 フェーズ戦略

全 first-party チャンネルの analytics を一覧表示する dashboard を、PoC (Python) → 本実装 (TS) の 2 フェーズで構築する。

## Context

運営者は 5 チャンネル前後を単独で運営しており、各チャンネルの analytics は `/analytics-collect` で個別に収集済み。しかし全チャンネルを横断して見渡す手段がなく、チャンネル間のパフォーマンス比較や注力判断に毎回個別のデータを突き合わせる手間が発生していた。

## Considered Options

### データソース

1. **既存 JSON スナップショットを読む (採用)** — 各チャンネルの `data/analytics_data_*.json` を読むだけ。収集と表示の責務分離
2. **ダッシュボード起動時に API 直接取得** — リアルタイムだが API クォータ消費、収集ロジックの二重実装

### チャンネル発見

1. **`~/.config/tayk/channels.json` レジストリ (採用)** — パスのみの配列。表示名は `config/channel/meta.json` から動的解決
2. **CLI 引数で都度指定** — スケールしない
3. **ディレクトリ規約で自動発見** — ファイルシステム配置がバラバラだと漏れる

### 技術スタック

1. **PoC: Python `yt-dashboard` CLI + 生 HTML (採用)** — 今の Python 環境で即動く。データフローの検証が目的
2. **本実装: `packages/dashboard` / `Bun.serve` / React + Vite + Spell UI (採用)** — TS 移行 (epic #727) の一部として構築。Hono 等のフレームワークは入れず `Bun.serve` 直接
3. **Python 側にフル実装** — cutover 控えで捨てコードになる。却下

### コンポーネントライブラリ

1. **Spell UI + Recharts 補完 (採用)** — コピペベース + Tailwind CSS。extensions/ と一貫したスタック。チャートが不足時は Recharts で補完
2. **shadcn/ui** — 同じコピペモデルだが Spell UI のチャート品質を優先
3. **Tremor** — ダッシュボード特化だがカスタマイズ自由度が低い

## Decision

### Phase 1: PoC (Python)

- `yt-dashboard` CLI を `pyproject.toml` に登録
- `~/.config/tayk/channels.json` からチャンネルパスを読み取り
- 各チャンネルの最新 `data/analytics_data_*.json` を集約
- Python HTTP サーバーで生 HTML を配信（UI は最小限）
- 表示: チャンネル概要一覧 + 動画別パフォーマンス (2 階層)

### Phase 2: 本実装 (TS)

- `packages/dashboard` を monorepo に追加
- `Bun.serve` で API (JSON) + Vite ビルド済み静的ファイルを配信
- React + Vite + Spell UI + Recharts
- `tayk dashboard` サブコマンドから起動
- channel registry の読み込みロジックは PoC で検証済みの設計を移植

### 共通制約

- dashboard はビューア専用。データ収集は `/analytics-collect` の責務
- 認証不要 — 全チャンネルが同一 Google アカウント配下、ローカルファイル読み取りのみ
- 単一運営者専用 — マルチテナント機能は設けない

## Consequences

- channel registry (`~/.config/tayk/channels.json`) が新たな設定ファイルとして増える。チャンネル追加時にパスの登録が必要
- PoC の Python コードは cutover 後に削除対象。本実装への知見移転が目的であり、長期メンテナンスはしない
- `packages/dashboard` は `@youtube-automation/core` の analytics service に依存する。core 側の analytics export が安定している必要がある
