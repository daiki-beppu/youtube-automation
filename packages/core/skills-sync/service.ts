import { readdir } from "node:fs/promises";
import { resolve } from "node:path";

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
// code-point 昇順で返す。存在しない source は readdir が reject して fail fast する。
export const listSkillsService = async (
  input: SkillListInput
): Promise<SkillListOutput> => {
  const { skillsDir } = SkillListInputSchema.parse(input);
  const source = skillsDir === undefined ? DEFAULT_SKILLS_DIR : skillsDir;

  const entries = await readdir(source, { withFileTypes: true });
  const skills = entries
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .toSorted();

  return SkillListOutputSchema.parse({ skills, source });
};
