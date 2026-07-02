# JSON-only config: packages/core から YAML 依存を排除

## Status

accepted (2026-06-15)。実装は `feat/ts-rewrite` 上で進行中（cutover #790 で main へ反映予定）。

## Context

Python 版では設定ファイルが 2 フォーマットに分裂していた:

- `config/channel/*.json` (12 種) — チャンネル設定。`json.load` で読む
- `config/skills/*.yaml` (16 種) + `.claude/skills/*/config.default.yaml` — スキル設定。`yaml.safe_load` で読み、default と channel override を `_deep_merge()` で再帰マージ
- `collections/*/20-documentation/suno-patterns.yaml` — 制作データ。`yaml.safe_load` で読む

TS (bun) 移行 (ADR-0001) にあたり、`packages/core` が 2 つのパーサー (`JSON.parse` + `js-yaml`) を抱える構造を維持するか、統一するかの判断が必要になった。

## Decision

`packages/core` が読み書きするファイルはすべて **JSON** に統一する。YAML パーサー依存 (`js-yaml` 等) を `packages/core` に追加しない。

具体的な変更:

1. **skill config**: `config/skills/<skill>.yaml` → `config/skills/<skill>.json`。`config.default.yaml` は廃止し、zod schema の `.default()` が省略キーを補完する。deep merge も廃止
2. **suno-patterns**: `suno-patterns.yaml` → `suno-patterns.json`
3. **channel config**: 変更なし (既に JSON)
4. **外部ツール所有ファイル**: 変更なし (CI `.yml` / `lefthook.yml` / `.takt/*.yaml` / `pnpm-lock.yaml` 等はそのまま)

YAML コメントが担っていた設定説明は zod schema の `.describe()` に集約する。

## Why

- **パーサー依存ゼロ**: `JSON.parse` は bun / Node.js の built-in。`js-yaml` を追加すると依存ツリーが増え、bundle size / supply chain risk が上がる
- **zod 親和性**: ADR-0002/0003 で zod schema を source of truth と確定済み。zod → JSON Schema は標準変換パスがあるが、YAML Schema という標準は存在しない
- **AI agent 最適化**: config の読み書きは AI agent が行う前提。AI は JSON を native に扱える (LLM の tool use / structured output が JSON ベース)。YAML のインデント崩れ・暗黙型変換 (`yes` → `true`) による認識齟齬リスクを排除
- **deep merge 廃止の合理性**: AI が差分だけ書いて merge される暗黙ルール (dict は再帰、list は上書き) より、フルファイル 1 本の方が認識齟齬が少ない。zod `.default()` + `.optional()` が「キー省略 = デフォルト」を型安全に表現する

## Considered Options

- **YAML に統一**: トークン効率は約 27% 良い (実測: content.json 1,566 chars → YAML 1,150 chars)。しかし `js-yaml` 依存の追加、zod との相互変換パス不在、AI 生成時のインデント崩れリスクが代償。TS エコシステム (`tsconfig.json`, `package.json`) も JSON native
- **JSONC (コメント付き JSON)**: `tsconfig.json` が採用するフォーマット。コメントを残せるが、config を AI が編集する前提では zod `.describe()` が説明を担うためコメントの必要性が低い。パーサーも `JSON.parse` ではなく別途必要
- **ハイブリッド (channel = JSON, skill = YAML のまま)**: 現状維持に近いが `packages/core` に YAML パーサー依存が残る。「core が読むファイルの統一」というスコープの趣旨に反する
- **deep merge を維持して JSON 化のみ**: フォーマットだけ変えて merge ロジックを残す。AI が 2 ファイル (default + override) を読んで merge ルールを理解する必要があり、認識齟齬リスクが残る

## Migration

cutover (#790) 時に一括実行。Python 側は触らない (throwaway code):

1. 上流: `.claude/skills/*/config.default.yaml` を削除 (zod `.default()` に吸収)
2. 下流: `config/skills/*.yaml` → `config/skills/*.json` に変換する migration script を cutover issue に含める
3. 下流: `suno-patterns.yaml` → `suno-patterns.json` に変換 (同上)
4. `yt-skills sync` (TS 版): `config.default.json` の配布を廃止。skill の zod schema が default を内包

## Consequences

- `packages/core/package.json` に `js-yaml` を追加しない (依存ゼロの enforcement)
- cutover migration script に skill config + suno-patterns の YAML → JSON 変換を含める
- 全 skill の zod schema に `.describe()` で設定説明を記述する (YAML コメントの移植)
- `config/channel/` と `config/skills/` のディレクトリ分離は維持 (責務・ライフサイクルが異なる)

## Related

- ADR-0001: Python → TypeScript(bun) big-bang 移行 (前提)
- ADR-0002: Service-first architecture / zod schema as source of truth (zod 採用の根拠)
- ADR-0003: Service-boundary contracts (zod `.describe()` / `.default()` の活用)
- Epic #727: TS rewrite
- Cutover #790: migration script の実行タイミング
