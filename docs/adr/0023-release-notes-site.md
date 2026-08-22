# Blume と Cloudflare Pages で公開リリースノートを配信する

## Status

accepted (2026-08-01, #3056)

## Context

GitHub Release の本文だけでは、本体と Chrome 拡張を横断して更新内容を探しにくい。運営者向け digest をそのまま公開すると内部の issue・PR 番号や実装名が漏れるため、公開表記を検証できる Markdown と、一覧・詳細を閲覧できる静的サイトが必要である。一方、現行 Python package の install や release に Node.js を持ち込んではならない。

## Decision

- `docs/release-notes/*.md` を公開コンテンツの SSOT とし、共通 frontmatter schema で本体と Chrome 拡張を区別する。
- `site/` に Blume workspace を置き、一覧・詳細ページと公開表記の検証を所有させる。これは ADR-0021 の TypeScript 禁止原則に対する静的サイト限定例外であり、tayk core や削除済み `packages/` を復活させない。
- lockfile を commit し、Nix の固定 Node.js / pnpm で `install --frozen-lockfile`、`check`、`test`、`build` を行う。
- `site/.blume/` と `site/dist/` は再生成可能な成果物として git 管理しない。
- Cloudflare Pages を配信境界とし、pull request は preview、`main` は production とする。品質検証 workflow と deploy workflow は分離する。
- onboarding の exact 4 path（`/onboarding`、`/onboarding/`、`/onboarding.md`、`/onboarding.mdx`）は Production / Preview とも Pages の静的 asset として直接配信する。Pages Function やクエリパラメータによる gate は設けず、`noindex` と公開導線からの除外で非掲載境界を維持する。
- Python wheel / sdist は従来の Hatch allowlist を維持し、`site/` の source・依存・生成物を一切同梱しない。実 archive の配布境界を pytest で検証する。

## Consequences

- 公開ノートの追加時は Markdown 契約とサイト build の両方が CI gate になる。
- サイト障害や Node dependency は Python CLI と下流チャンネルの install を壊さない。
- build output を repository から直接配信せず、Cloudflare Pages が commit から再生成する。
- onboarding は通常 URL から直接閲覧できる一方、トップページ、navigation、検索、AI 出力、sitemap には掲載せず、検索エンジン向け `noindex` を維持する。runtime と secret の運用は不要になる。

## Considered Options

- **GitHub Release のみ**: 本体と拡張の横断一覧、公開表記 schema、サイト内導線を提供できないため不採用。
- **手書き Astro サイト**: リリースノート向けの collection・検索・agent-readable output を重複実装するため不採用。
- **Python package へのサイト同梱**: 公開サイトとローカル CLI の release lifecycle を結合し、Node build を Python 配布へ持ち込むため不採用。

## Related

- ADR-0021（TypeScript 境界）
- `docs/development.md::リリースノートサイト開発`
- #3052 / #3054 / #3055 / #3056
