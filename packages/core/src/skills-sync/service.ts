import { existsSync } from "node:fs";
import {
  cp,
  copyFile,
  lstat,
  mkdir,
  readdir,
  readlink,
  rm,
  symlink,
} from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";

import { createService } from "../service-frame.ts";
import {
  SkillListInputSchema,
  SkillListOutputSchema,
  SkillSyncInputSchema,
  SkillSyncOutputSchema,
} from "./schema.ts";
import type { SkillSyncOutput } from "./schema.ts";

// 同梱 skills resource の既定パス。import.meta 基点で packages/cli/_skills を解決する
// (packages/core/src/skills-sync/service.ts → ../../../cli/_skills)。_skills は .claude/skills への symlink。
const DEFAULT_SKILLS_DIR = resolve(
  import.meta.dirname,
  "..",
  "..",
  "..",
  "cli",
  "_skills"
);

// 同梱 CLAUDE.md テンプレートの既定パス (#742)。_skills と同じく import.meta 基点で
// packages/cli/_claude_md/CLAUDE.template.md を解決する。_claude_md は .claude/CLAUDE.template.md への symlink。
const CLAUDE_MD_SOURCE = resolve(
  import.meta.dirname,
  "..",
  "..",
  "..",
  "cli",
  "_claude_md",
  "CLAUDE.template.md"
);

// 配布レイアウトの契約パスセグメント。複数箇所で参照するため 1 箇所で定義する。
const CLAUDE_DIR = ".claude";
const SKILLS_DIRNAME = "skills";
const CLAUDE_MD_FILENAME = "CLAUDE.md";
const AGENTS_DIR = ".agents";

// 資産ごとの既定ターゲット (CWD 相対)。CLI が --target を渡さないとき service が埋める。
const DEFAULT_TARGETS = {
  "claude-md": join(CLAUDE_DIR, CLAUDE_MD_FILENAME),
  skills: join(CLAUDE_DIR, SKILLS_DIRNAME),
} as const;

// Codex 探索パス <repo>/.agents/skills が指す相対 symlink ターゲット
// (Python `_AGENTS_SKILLS_LINK_TARGET` と一致)。POSIX 区切りで固定する。
const AGENTS_SKILLS_LINK_TARGET = `../${CLAUDE_DIR}/${SKILLS_DIRNAME}`;

// 1 skill = 1 ディレクトリ。非ディレクトリは除外し、Python `sorted(...)` と同じ
// code-point 昇順で返す。内部は throw OK で、入力 / 出力検証と `ServiceError`
// 変換は `createService` が担う (ADR-0003 §1)。マッピング:
//   - schema 違反 (skillsDir 非文字列 / 未知キー) → err(domain "validation")  (ZodError)
//   - 存在しない source (readdir ENOENT)           → err(domain "io")          (未 prefix Error)
export const listSkillsService = createService(
  SkillListInputSchema,
  SkillListOutputSchema,
  async ({ skillsDir }) => {
    const source = skillsDir === undefined ? DEFAULT_SKILLS_DIR : skillsDir;

    const entries = await readdir(source, { withFileTypes: true });
    const skills = entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .toSorted();

    return { skills, source };
  }
);

const resolveSyncTarget = (
  asset: "claude-md" | "skills",
  target: string | undefined
): string => resolve(target ?? DEFAULT_TARGETS[asset]);

// 配布先が標準レイアウト <repo>/.claude/skills か。ここでのみ .agents/skills mirror を試行する
// (それ以外は repo root を特定できないため mirror しない)。
const isStandardSkillsLayout = (targetDir: string): boolean =>
  basename(targetDir) === SKILLS_DIRNAME &&
  basename(dirname(targetDir)) === CLAUDE_DIR;

// 存在チェック付き lstat。symlink を辿らず、存在しなければ null。ENOENT 以外は
// 握りつぶさず再 throw する (Fail Fast — 想定外の I/O エラーは呼び出し側へ伝播)。
const lstatOrNull = async (path: string) => {
  try {
    return await lstat(path);
  } catch (error) {
    if (
      typeof error === "object" &&
      error !== null &&
      (error as { code?: unknown }).code === "ENOENT"
    ) {
      return null;
    }
    throw error;
  }
};

// skill ディレクトリを deep copy する (Python `copytree(symlinks=False)` 相当で
// dereference)。既存かつ非 force なら skip。
const copyDirEntry = async (
  src: string,
  dest: string,
  force: boolean
): Promise<"created" | "skipped"> => {
  if (!force && existsSync(dest)) {
    return "skipped";
  }
  await cp(src, dest, { dereference: true, force: true, recursive: true });
  return "created";
};

// 単一ファイルをコピーする。既存かつ非 force なら skip。
const copyFileEntry = async (
  src: string,
  dest: string,
  force: boolean
): Promise<"created" | "skipped"> => {
  if (!force && existsSync(dest)) {
    return "skipped";
  }
  await copyFile(src, dest);
  return "created";
};

// <repo>/.agents/skills を ../.claude/skills への相対 symlink として冪等に作成する。
//   - 既存の正しい symlink + 非 force → "skipped"
//   - 不在 / force / 不整合       → 張り直して "linked"
//   - 作成不能 (.agents が通常ファイル等) → "unsupported" (AC#4: 警告のみで sync 継続)
const ensureAgentsSkillsLink = async (
  repoRoot: string,
  force: boolean
): Promise<"linked" | "skipped" | "unsupported"> => {
  const linkPath = join(repoRoot, AGENTS_DIR, SKILLS_DIRNAME);
  try {
    await mkdir(join(repoRoot, AGENTS_DIR), { recursive: true });
    const existing = await lstatOrNull(linkPath);
    if (
      existing &&
      !force &&
      existing.isSymbolicLink() &&
      (await readlink(linkPath)) === AGENTS_SKILLS_LINK_TARGET
    ) {
      return "skipped";
    }
    if (existing) {
      await rm(linkPath, { force: true, recursive: true });
    }
    await symlink(AGENTS_SKILLS_LINK_TARGET, linkPath);
    return "linked";
  } catch {
    return "unsupported";
  }
};

const syncSkillsAsset = async (
  targetDir: string,
  force: boolean
): Promise<SkillSyncOutput> => {
  await mkdir(targetDir, { recursive: true });
  const dirents = await readdir(DEFAULT_SKILLS_DIR, { withFileTypes: true });
  const names = dirents
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .toSorted();

  const entries: SkillSyncOutput["entries"] = [];
  for (const name of names) {
    const result = await copyDirEntry(
      join(DEFAULT_SKILLS_DIR, name),
      join(targetDir, name),
      force
    );
    entries.push({ name, result });
  }

  const agentsSkillsLink = isStandardSkillsLayout(targetDir)
    ? await ensureAgentsSkillsLink(dirname(dirname(targetDir)), force)
    : null;

  return { agentsSkillsLink, asset: "skills", entries, target: targetDir };
};

const syncClaudeMdAsset = async (
  targetFile: string,
  force: boolean
): Promise<SkillSyncOutput> => {
  await mkdir(dirname(targetFile), { recursive: true });
  const result = await copyFileEntry(CLAUDE_MD_SOURCE, targetFile, force);
  return {
    agentsSkillsLink: null,
    asset: "claude-md",
    entries: [{ name: basename(targetFile), result }],
    target: targetFile,
  };
};

// 同梱資産 (skills / claude-md) を対象リポジトリへ配布する (#742)。"all" は CLI sugar の
// ため schema enum で弾かれ validation error になる。境界変換は `createService` に集約する。
export const syncAssetService = createService(
  SkillSyncInputSchema,
  SkillSyncOutputSchema,
  async ({ asset, force, target }) => {
    const resolved = resolveSyncTarget(asset, target);
    return asset === "skills"
      ? await syncSkillsAsset(resolved, force)
      : await syncClaudeMdAsset(resolved, force);
  }
);
