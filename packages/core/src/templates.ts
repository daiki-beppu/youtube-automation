// 説明文テンプレートローダー（Python `src/youtube_automation/templates/` の移植）。
//
// テンプレートは `packages/core/templates/` に配置し、`import.meta.url` 基準で解決する
// （process.cwd() に依存しないため、呼び出し側の作業ディレクトリに関係なく読める）。

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ValidationError } from "./errors.ts";

const TEMPLATES_DIR = join(import.meta.dirname, "..", "templates");

// 配布する既知テンプレート名。未知名は Fail Fast で弾く。
const TEMPLATE_NAMES = new Set(["complete_collection", "individual_track"]);

/** `<name>.md` テンプレートを文字列で読み込む。未知名は ValidationError。 */
export const loadTemplate = (name: string): string => {
  if (!TEMPLATE_NAMES.has(name)) {
    throw new ValidationError(
      `未知のテンプレート名: ${name}（既知: ${[...TEMPLATE_NAMES].join(", ")}）`
    );
  }
  return readFileSync(join(TEMPLATES_DIR, `${name}.md`), "utf-8");
};
