# extensions（Chrome 拡張開発）

- `extensions/` 配下は WXT + React + TypeScript + Tailwind CSS（pnpm）。規約詳細は `docs/development.md` と `extensions/README.md`

## shadcn/ui の docs-first 手順

`components.json` がある workspace の UI を変更するときは、実装前に公式 `/shadcn` skill を使う。

1. 対象 workspace で `pnpm dlx shadcn@latest info --json` を実行し、`style: base-vega`、Base UI、Tailwind v4、alias、resolved path を確認する。
2. 対象 component の `pnpm dlx shadcn@latest docs <component>` が返す公式 docs を読む。
3. 新規 component は `search` / `view` で公式 registry を確認する。既存 component の更新は `add <component> --dry-run` と、対象ファイルごとの `add <component> --diff <file>` で差分を確認する。
4. `--overwrite` で機械置換せず、ローカル variant、semantic token、`data-*`、ARIA、extension固有の portal / Shadow DOM 契約を保持して差分をmergeする。

公式skillの導入元とrevisionはルートの `skills-lock.json` を単一のprovenanceとする。`SKILL.md` 本文はupstreamを維持し、frontmatterの `description` だけを本リポジトリのstrict YAML規約へ適合させる。
