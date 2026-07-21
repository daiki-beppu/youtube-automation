# マルチチャンネル dashboard: Python 配信 + React 表示

## Status

accepted (2026-06-23)、amended (2026-07-21, #2386)。旧 2 フェーズ案を廃止し、本リポジトリ内で保守する単一構成へ置き換える。

## Context

運営者は複数の first-party チャンネルを持ち、各チャンネルの `data/analytics_data_*.json` を個別に確認している。収集済みデータを横断表示する読み取り専用 UI が必要だが、dashboard 起動を Analytics 収集や別リポジトリの tayk 開発へ結合させないことも必要である。

## Decision

### 責務境界

- Python HTTP server の `yt-dashboard` が channel registry、read model、JSON API、loopback 限定配信を担当する。
- `dashboard/` の React + Vite frontend は JSON API の表示だけを担当し、filesystem、YouTube API、更新 CLI を直接呼ばない。
- HTTP server の既定 bind は `127.0.0.1:8765`。認証や外部公開は提供しない。
- dashboard は読み取り専用であり、欠損・破損したチャンネルは部分エラーとして表示し、他チャンネルの表示を止めない。
- 単一チャンネル用 `yt-kpi-dashboard` と収集用 `/analytics-collect` の責務は変更しない。

### frontend の配置と UI 契約

- frontend workspace はリポジトリ直下の `dashboard/` に置く。削除済みの `packages/` は復活させない。
- React、Vite、TypeScript、Tailwind CSS v4、shadcn/ui の Base UI スタイルを使う。
- `Card`、`Table`、`Badge`、`Skeleton`、`Empty`、`Alert`、`Chart` など shadcn/ui component を組み合わせ、同等の独自 primitive を増やさない。
- 色は raw 値ではなく semantic token を使い、keyboard focus と loading / empty / partial error を視覚・ARIA の両方で判別可能にする。
- `extensions/shared-ui` は Chrome extension の Shadow DOM と独立した workspace/package 境界を持つため、dashboard から直接 import しない。Base UI、Tailwind CSS v4、semantic token、theme class という契約だけを揃え、dashboard 自身の `components.json` と生成 component を持つ。
- component 追加前に対象 workspace で `shadcn info` と registry/docs を確認する。install 済み component の更新は dry-run/diff 後に行う。

### build と配布

- Vite は `dashboard/index.html` を入口に production asset を生成する。Python server と同一 origin の `/` から配信できるよう build base を設定する。
- build output は `src/youtube_automation/dashboard_dist/` に生成し、Python package data として wheel / sdist の双方へ同梱する。runtime はソース workspace や Node.js に依存せず `importlib.resources` から asset を解決する。
- build 済み asset は配布契約なので commit 対象とし、frontend source 変更時に `build` と wheel smoke test で同期を検証する。`node_modules/`、coverage、Playwright artifact は commit しない。
- Python package build が Node toolchain を暗黙実行する構成にはしない。frontend build は明示 command/CI step で先に完了させ、hatch は完成済み package data を収録する。

### 品質ゲート

- frontend: `lint`、`typecheck`、Vitest の `test`、Playwright の `test:e2e`、`build`。
- Python: registry/read model/server の対象 pytest、behavioral fast lane、unit-only 全体 pytest、Ruff。
- packaging: candidate wheel を非 editable installし、`yt-dashboard` が build asset と API を配信できる smoke test。

## Considered Options

1. **Python API/配信 + React/Vite + shadcn/ui（採用）** — 現行 Python データ経路と保守可能な UI を同じ配布物に収められる。
2. **Python + 生 HTML（不採用）** — component、accessibility、状態表示の規約を継続的に検証しにくい。
3. **frontend server を別プロセスで本番運用（不採用）** — 非 editable wheel が Node.js を要求し、配布境界が増える。
4. **`extensions/shared-ui` の直接 import（不採用）** — Chrome extension の workspace、Shadow DOM、release lifecycle を dashboard wheel に結合する。
5. **dashboard 起動時の YouTube API 取得（不採用）** — 表示と収集を混ぜ、クォータを消費する。

## Consequences

- 本リポジトリの TypeScript 禁止原則に `dashboard/` 限定の例外が生じる。例外は UI source/test/build config だけであり、tayk core や旧 `packages/` を戻す根拠にはならない。
- frontend source と package data の同期、wheel / sdist 同梱を CI で固定する必要がある。
- channel registry (`~/.config/tayk/channels.json`) が設定ファイルとして増える。

## Official references

- [shadcn/ui installation](https://ui.shadcn.com/docs/installation)
- [shadcn CLI](https://ui.shadcn.com/docs/cli)
- [Base UI overview](https://base-ui.com/react/overview/about)
- [Vite production build](https://vite.dev/guide/build)
- [Vite static assets](https://vite.dev/guide/assets.html)
- [Python Packaging User Guide: pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)

## Related

- ADR-0021（tayk は別リポジトリ。dashboard 限定例外）
- #2384 / #2385 / #2387
