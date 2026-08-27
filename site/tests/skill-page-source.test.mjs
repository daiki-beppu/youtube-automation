import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import {
  createSkillPageSource,
  parseSkillCategories,
  parseSkillMarkdown,
} from "../skill-page-source.ts";

const skillMarkdown = ({
  description = "Use when test。後続は /beta",
  name = "alpha",
  prerequisites = "",
} = {}) => `---
name: ${name}
description: ${JSON.stringify(description)}
---

## 前後工程

- \`前工程\`: \`なし\`
- \`後工程\`: \`/beta\`
${prerequisites}
## Task

INTERNAL INSTRUCTION MUST NOT LEAK
`;

const catalog = `# できることから skill を探す

## category one

| Skill | なにができるか |
|---|---|
| /alpha | alpha |

## category two

| Skill | なにができるか |
|---|---|
| /beta | beta |
`;

const createRepository = async () => {
  const root = await mkdtemp(join(tmpdir(), "skill-page-source-"));
  await mkdir(join(root, ".claude/skills/alpha"), { recursive: true });
  await mkdir(join(root, ".claude/skills/beta"), { recursive: true });
  await mkdir(join(root, "docs"), { recursive: true });
  await writeFile(
    join(root, ".claude/skills/alpha/SKILL.md"),
    skillMarkdown({ prerequisites: "\n## 前提\n\nalpha prerequisite\n\n" }),
    "utf8"
  );
  await writeFile(
    join(root, ".claude/skills/beta/SKILL.md"),
    skillMarkdown({ description: "Use when beta", name: "beta" }),
    "utf8"
  );
  await writeFile(join(root, "docs/features.md"), catalog, "utf8");
  return root;
};

test("frontmatter と公開2節だけを抽出する", () => {
  const parsed = parseSkillMarkdown(
    skillMarkdown({ prerequisites: "\n## 前提\n\nrequired\n\n" }),
    "alpha"
  );

  assert.equal(parsed.name, "alpha");
  assert.equal(parsed.description, "Use when test。後続は /beta");
  assert.equal(parsed.prerequisites, "required");
  assert.match(parsed.workflow, /後工程/);
  assert.doesNotMatch(parsed.workflow, /INTERNAL INSTRUCTION/);
});

test("description 欠損は該当 skill 名を示して拒否する", () => {
  const markdown = skillMarkdown().replace(/^description:.*\n/mu, "");
  assert.throws(
    () => parseSkillMarkdown(markdown, "alpha"),
    /alpha.*description/i
  );
});

test("features のカテゴリと skill 順を抽出する", () => {
  assert.deepEqual(parseSkillCategories(catalog), [
    { label: "category one", skills: ["alpha"] },
    { label: "category two", skills: ["beta"] },
  ]);
});

test("一覧と全 skill ページを生成し、参照をサイト内リンクへ変換する", async () => {
  const repositoryRoot = await createRepository();
  const source = createSkillPageSource({ repositoryRoot });
  const result = await source.load();

  assert.equal(result.entries.length, 3);
  assert.deepEqual(
    result.entries.map((entry) => entry.slug),
    ["/skills", "/skills/alpha", "/skills/beta"]
  );
  const alpha = result.entries.find((entry) => entry.slug === "/skills/alpha");
  assert.match(alpha.body.text, /\[\/beta\]\(\/skills\/beta\)/);
  assert.match(alpha.body.text, /## 前提\n\nalpha prerequisite/);
  assert.doesNotMatch(alpha.body.text, /Task|Gotchas|Subagent|INTERNAL/);
  const beta = result.entries.find((entry) => entry.slug === "/skills/beta");
  assert.doesNotMatch(beta.body.text, /## 前提/);
});

test("一覧と個別ページの先頭 H1 を title へ分離する", async () => {
  const repositoryRoot = await createRepository();
  const source = createSkillPageSource({ repositoryRoot });
  const result = await source.load();

  const index = result.entries.find((entry) => entry.slug === "/skills");
  const alpha = result.entries.find((entry) => entry.slug === "/skills/alpha");

  assert.equal(index.data.title, "発動条件から skill を使う");
  assert.match(index.body.text, /発動条件・前提・前後工程/);
  assert.match(index.body.text, /\[できることの 1 行要約から探す\]\(\/features\)/);
  assert.doesNotMatch(index.body.text, /^# /mu);
  assert.match(index.body.text, /^## category one$/mu);
  assert.match(index.raw, /^---\ntitle: "発動条件から skill を使う"\ntype: doc\n---\n\n/mu);
  assert.equal(alpha.data.title, "/alpha");
  assert.doesNotMatch(alpha.body.text, /^# /mu);
  assert.match(alpha.body.text, /^## 前提$/mu);
  assert.match(alpha.raw, /^---\ntitle: "\/alpha"\ntype: doc\n---\n\n/mu);
});

test("skill を追加するとカタログ更新前でも個別ページが増える", async () => {
  const repositoryRoot = await createRepository();
  const source = createSkillPageSource({ repositoryRoot });
  const before = await source.load();
  await mkdir(join(repositoryRoot, ".claude/skills/gamma"), { recursive: true });
  await writeFile(
    join(repositoryRoot, ".claude/skills/gamma/SKILL.md"),
    skillMarkdown({ description: "Use when gamma", name: "gamma" }),
    "utf8"
  );
  const after = await source.load();

  assert.equal(after.entries.length, before.entries.length + 1);
  assert(after.entries.some((entry) => entry.slug === "/skills/gamma"));
  assert.match(after.entries[0].body.text, /## 未分類/);
});

test("実リポジトリでは9カテゴリと全skillを生成する", async () => {
  const repositoryRoot = resolve(import.meta.dirname, "../..");
  const source = createSkillPageSource({ repositoryRoot });
  const result = await source.load();
  const skillDirectories = (
    await readFile(join(repositoryRoot, "docs/features.md"), "utf8")
  ).match(/^\| \/[a-z0-9-]+ /gmu);

  assert.equal(result.entries.length, 23);
  assert.equal(skillDirectories?.length, 22);
  assert.equal(parseSkillCategories(await readFile(join(repositoryRoot, "docs/features.md"), "utf8")).length, 9);
  assert.doesNotMatch(result.entries[0].body.text, /## 未分類/);
});

test("production build は一覧と22個の個別ページを公開する", async () => {
  const siteRoot = resolve(import.meta.dirname, "..");
  const index = await readFile(join(siteRoot, "dist/skills/index.html"), "utf8");
  const thumbnail = await readFile(
    join(siteRoot, "dist/skills/thumbnail/index.html"),
    "utf8"
  );
  const music = await readFile(join(siteRoot, "dist/skills/music/index.html"), "utf8");

  assert.match(index, /22 個の skill/);
  assert.match(index, /href="\/skills\/wf-new"/);
  assert.doesNotMatch(index, /href="\/skills\/masterup"/);
  assert.doesNotMatch(index, /href="\/skills\/flop-analysis"/);
  assert.doesNotMatch(index, /href="\/skills\/channel-status"/);
  assert.equal((index.match(/<h1\b/g) ?? []).length, 1);
  assert.match(index, /<h1[^>]*>発動条件から skill を使う<\/h1>/);
  assert.match(index, /href="\/features"/);
  assert.match(thumbnail, /--compare/);
  assert.match(thumbnail, /--test/);
  assert.match(thumbnail, /--iterate/);
  assert.match(thumbnail, /--loop/);
  // Blume's typography pass renders the CLI double hyphen as an en dash.
  assert.match(music, /–master/);
  assert.doesNotMatch(index, /href="\/skills\/thumbnail-compare"/);
  assert.doesNotMatch(index, /href="\/skills\/thumbnail-test"/);
  assert.doesNotMatch(index, /href="\/skills\/thumbnail-iterate"/);
  assert.doesNotMatch(index, /href="\/skills\/loop-video"/);
  assert.equal((thumbnail.match(/<h1\b/g) ?? []).length, 1);
  assert.match(thumbnail, /<h1[^>]*>\/thumbnail<\/h1>/);
  assert.match(thumbnail, /<h2[^>]*>.*?前提.*?<\/h2>/);
  assert.doesNotMatch(thumbnail, /Subagent Contract|run_in_background|Gotchas/);
});
