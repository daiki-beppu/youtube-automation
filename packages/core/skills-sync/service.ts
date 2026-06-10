import { readdir } from "node:fs/promises";
import { resolve } from "node:path";

import { toServiceError } from "../src/errors.ts";
import type { ServiceError } from "../src/errors.ts";
import { err, ok } from "../src/result.ts";
import type { Result } from "../src/result.ts";
import { SkillListInputSchema, SkillListOutputSchema } from "./schema.ts";
import type { SkillListInput, SkillListOutput } from "./schema.ts";

// 同梱 skills resource の既定パス。import.meta 基点で packages/cli/_skills を解決する
// (packages/core/skills-sync/service.ts → ../../cli/_skills)。_skills は .claude/skills への symlink。
const DEFAULT_SKILLS_DIR = resolve(
  import.meta.dirname,
  "..",
  "..",
  "cli",
  "_skills"
);

// 1 skill = 1 ディレクトリ。非ディレクトリは除外し、Python `sorted(...)` と同じ
// code-point 昇順で返す。内部は throw OK で、境界の try/catch で `toServiceError`
// 経由の `Result` に集約する (ADR-0003 §1)。マッピング:
//   - schema 違反 (skillsDir 非文字列 / 未知キー) → err(domain "validation")  (ZodError)
//   - 存在しない source (readdir ENOENT)           → err(domain "io")          (未 prefix Error)
export const listSkillsService = async (
  input: SkillListInput
): Promise<Result<SkillListOutput, ServiceError>> => {
  try {
    const { skillsDir } = SkillListInputSchema.parse(input);
    const source = skillsDir === undefined ? DEFAULT_SKILLS_DIR : skillsDir;

    const entries = await readdir(source, { withFileTypes: true });
    const skills = entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .toSorted();

    return ok(SkillListOutputSchema.parse({ skills, source }));
  } catch (error) {
    return err(toServiceError(error));
  }
};
