import { existsSync, realpathSync } from "node:fs";
import { readdir, readFile } from "node:fs/promises";
import { join, resolve, sep } from "node:path";
import type { ContentSource, SourceEntry } from "blume/sources/types";
import { extractMarkdownTitle } from "./markdown-title.ts";
import { operatorDocReleaseField } from "./operator-doc-source.ts";

const GITHUB_SKILL_BASE =
  "https://github.com/daiki-beppu/youtube-automation/blob/main/.claude/skills/";
const SKILL_NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/u;
export const DEV_ONLY_SKILL_NAMES = new Set([
  "automation-release",
  "hallmark",
  "shadcn",
]);

export interface SkillPage {
  readonly apiCalls?: string;
  readonly artifacts: string;
  readonly category?: string;
  readonly description: string;
  readonly name: string;
  readonly prerequisites?: string;
  readonly triggerPhrases: readonly string[];
  readonly workflow: string;
}

export interface SkillCategory {
  readonly label: string;
  readonly skills: readonly string[];
}

const extractSection = (markdown: string, heading: string): string | undefined => {
  const lines = markdown.split("\n");
  const start = lines.findIndex((line) => line === `## ${heading}`);
  if (start === -1) return undefined;
  const end = lines.findIndex(
    (line, index) => index > start && line.startsWith("## ")
  );
  return lines.slice(start + 1, end === -1 ? undefined : end).join("\n").trim();
};

const parseQuotedField = (
  frontmatter: string,
  field: string,
  skillName: string
): string => {
  const match = frontmatter.match(
    new RegExp(`^${field}:\\s*("(?:[^"\\\\]|\\\\.)*")\\s*$`, "mu")
  );
  if (!match) {
    throw new Error(`Skill ${skillName} is missing a double-quoted ${field}`);
  }
  try {
    return JSON.parse(match[1]) as string;
  } catch (error) {
    throw new Error(`Skill ${skillName} has an invalid ${field}`, { cause: error });
  }
};

export const parseSkillMarkdown = (
  markdown: string,
  directoryName: string
): SkillPage => {
  const frontmatterMatch = markdown.match(/^---\n([\s\S]*?)\n---(?:\n|$)/u);
  if (!frontmatterMatch) {
    throw new Error(`Skill ${directoryName} is missing frontmatter`);
  }
  const nameMatch = frontmatterMatch[1].match(/^name:\s*([^\s]+)\s*$/mu);
  const name = nameMatch?.[1];
  if (!name || !SKILL_NAME_PATTERN.test(name)) {
    throw new Error(`Skill ${directoryName} has an invalid name`);
  }
  if (name !== directoryName) {
    throw new Error(
      `Skill ${directoryName} frontmatter name does not match directory: ${name}`
    );
  }
  const workflow = extractSection(markdown, "前後工程");
  if (!workflow) {
    throw new Error(`Skill ${name} is missing section: 前後工程`);
  }
  const artifacts = extractSection(markdown, "成果物");
  if (!artifacts) {
    throw new Error(`Skill ${name} is missing section: 成果物`);
  }
  const description = parseQuotedField(frontmatterMatch[1], "description", name);
  return {
    apiCalls: extractSection(markdown, "想定 API call 数"),
    artifacts,
    description,
    name,
    prerequisites: extractSection(markdown, "前提"),
    triggerPhrases: [
      ...description.matchAll(/「([^」]+)」|『([^』]+)』/gu),
    ].map((match) => match[1] ?? match[2]),
    workflow,
  };
};

export const parseSkillCategories = (markdown: string): SkillCategory[] => {
  const categories: Array<{ label: string; skills: string[] }> = [];
  let current: { label: string; skills: string[] } | undefined;
  for (const line of markdown.split("\n")) {
    const heading = line.match(/^## ([^#].*)$/u);
    if (heading) {
      current = { label: heading[1].trim(), skills: [] };
      categories.push(current);
      continue;
    }
    const row = line.match(
      /^\|\s*(?:\[`)?\/([a-z0-9]+(?:-[a-z0-9]+)*)(?:`?\]\(\/skills\/[^)]+\))?\s*\|/u
    );
    if (row && current) current.skills.push(row[1]);
  }
  return categories.filter((category) => category.skills.length > 0);
};

const linkSkillReferences = (
  markdown: string,
  skillNames: ReadonlySet<string>
): string => {
  let linked = markdown;
  const names = [...skillNames].sort((left, right) => right.length - left.length);
  for (const name of names) {
    const escaped = name;
    linked = linked.replace(
      new RegExp("`/" + escaped + "`", "gu"),
      `[/${name}](/skills/${name})`
    );
    linked = linked.replace(
      new RegExp(`(?<![\\w/.(\\[])\\/${escaped}(?![\\w-]|\\)\\])`, "gu"),
      `[/${name}](/skills/${name})`
    );
  }
  return linked;
};

const codeSpanFlags = (description: string): string =>
  description.replace(/(?<![\w`])(--[A-Za-z0-9][A-Za-z0-9-]*)(?![\w-]|`)/gu, "`$1`");

const renderSkillPage = (
  skill: SkillPage,
  skillNames: ReadonlySet<string>
): string => {
  const sections = [
    `# /${skill.name}`,
    linkSkillReferences(codeSpanFlags(skill.description), skillNames),
    "## リファレンス",
  ];
  if (skill.triggerPhrases.length > 0) {
    sections.push(
      "### 発動フレーズ",
      skill.triggerPhrases.map((phrase) => `- ${phrase}`).join("\n")
    );
  }
  sections.push(
    "### 前後工程",
    linkSkillReferences(skill.workflow, skillNames),
    "### 成果物",
    linkSkillReferences(skill.artifacts, skillNames)
  );
  if (skill.apiCalls) {
    sections.push(
      "### 想定 API call 数",
      linkSkillReferences(skill.apiCalls, skillNames)
    );
  }
  if (skill.prerequisites) {
    sections.push(
      "### 前提",
      linkSkillReferences(skill.prerequisites, skillNames)
    );
  }
  return `${sections.join("\n\n")}\n`;
};

const renderSkillIndex = (
  skills: readonly SkillPage[],
  categories: readonly SkillCategory[]
): string => {
  const byName = new Map(skills.map((skill) => [skill.name, skill]));
  const categorized = new Set(categories.flatMap((category) => category.skills));
  const sections = categories.map((category) => {
    const rows = category.skills.map((name) => {
      const skill = byName.get(name);
      if (!skill) {
        throw new Error(`Skill catalog references missing skill: ${name}`);
      }
      return `- [/${name}](/skills/${name}) — ${skill.description}`;
    });
    return `## ${category.label}\n\n${rows.join("\n")}`;
  });
  const uncategorized = skills
    .filter((skill) => !categorized.has(skill.name))
    .map(
      (skill) =>
        `- [/${skill.name}](/skills/${skill.name}) — ${skill.description}`
    );
  if (uncategorized.length > 0) {
    sections.push(`## 未分類\n\n${uncategorized.join("\n")}`);
  }
  return `# 発動条件から skill を使う\n\n${skills.length} 個の skill について、発動条件・前提・前後工程を確認できます。目的に合う skill がまだ決まっていない場合は、[できることの 1 行要約から探す](/features)ページへ進んでください。\n\n${sections.join("\n\n")}\n`;
};

const assertInsideRepository = (repositoryRoot: string, path: string): string => {
  const realRoot = realpathSync(repositoryRoot);
  const realPath = realpathSync(path);
  if (realPath !== realRoot && !realPath.startsWith(`${realRoot}${sep}`)) {
    throw new Error(`Skill source escapes repository: ${path}`);
  }
  return realPath;
};

const sourceEntry = (
  ref: string,
  slug: string,
  markdown: string,
  editUrl?: string
): SourceEntry => {
  const { text, title } = extractMarkdownTitle(markdown);
  return {
    body: { format: "md", text },
    data: {
      kind: operatorDocReleaseField,
      released_at: operatorDocReleaseField,
      summary: operatorDocReleaseField,
      title,
      type: "doc",
      version: operatorDocReleaseField,
    },
    ...(editUrl ? { editUrl } : {}),
    raw: `---\ntitle: ${JSON.stringify(title)}\ntype: doc\n---\n\n${text}`,
    ref,
    slug,
  };
};

const loadSkillEntries = async (repositoryRoot: string): Promise<SourceEntry[]> => {
  const skillsRoot = resolve(repositoryRoot, ".claude/skills");
  const catalogPath = resolve(repositoryRoot, "docs/features.md");
  if (!existsSync(skillsRoot) || !existsSync(catalogPath)) {
    throw new Error("Skill pages require .claude/skills and docs/features.md");
  }
  assertInsideRepository(repositoryRoot, skillsRoot);
  assertInsideRepository(repositoryRoot, catalogPath);
  const directories = (await readdir(skillsRoot, { withFileTypes: true }))
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .filter((name) => !DEV_ONLY_SKILL_NAMES.has(name))
    .sort();
  const skills = await Promise.all(
    directories.map(async (directoryName) => {
      const path = join(skillsRoot, directoryName, "SKILL.md");
      if (!existsSync(path)) return undefined;
      const realPath = assertInsideRepository(repositoryRoot, path);
      return parseSkillMarkdown(await readFile(realPath, "utf8"), directoryName);
    })
  );
  const pages = skills.filter((skill): skill is SkillPage => skill !== undefined);
  const names = new Set(pages.map((skill) => skill.name));
  if (names.size !== pages.length) throw new Error("Duplicate skill names detected");
  const categories = parseSkillCategories(await readFile(catalogPath, "utf8"));
  const entries = pages.map((skill) => {
    const text = renderSkillPage(skill, names);
    return sourceEntry(
      `${skill.name}.md`,
      `/skills/${skill.name}`,
      text,
      `${GITHUB_SKILL_BASE}${skill.name}/SKILL.md`
    );
  });
  entries.unshift(
    sourceEntry(
      "index.md",
      "/skills",
      renderSkillIndex(pages, categories),
      "https://github.com/daiki-beppu/youtube-automation/blob/main/docs/features.md"
    )
  );
  return entries;
};

export const createSkillPageSource = (options: {
  readonly repositoryRoot: string;
}): ContentSource => {
  const repositoryRoot = resolve(options.repositoryRoot);
  return {
    load: async () => ({ diagnostics: [], entries: await loadSkillEntries(repositoryRoot) }),
    name: "skill-pages",
    read: async (ref) => {
      const entry = (await loadSkillEntries(repositoryRoot)).find(
        (candidate) => candidate.ref === ref
      );
      if (!entry) throw new Error(`Unknown skill page source: ${ref}`);
      return entry.body.text;
    },
    staged: true,
    validate: () => {
      if (!existsSync(resolve(repositoryRoot, ".claude/skills"))) {
        throw new Error("Skill source root not found: .claude/skills");
      }
    },
  };
};
