import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import {
  createSkillPageSource,
  parseSkillCategories,
  parseSkillMarkdown,
  skillSidebarRoutes,
} from "../skill-page-source.ts";

const skillMarkdown = ({
  description = "Use when 「テストして」「試して」。--collect の後続は /beta",
  name = "alpha",
  prerequisites = "",
  apiCalls = "",
} = {}) => `---
name: ${name}
description: ${JSON.stringify(description)}
---

## 前後工程

- \`前工程\`: \`なし\`
- \`後工程\`: \`/beta\`
${prerequisites}
## 成果物

- \`output.md\`
${apiCalls}
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
  await mkdir(join(root, ".claude/skills/hallmark"), { recursive: true });
  await mkdir(join(root, "docs"), { recursive: true });
  await mkdir(join(root, "site/skill-docs"), { recursive: true });
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
  await writeFile(
    join(root, ".claude/skills/hallmark/SKILL.md"),
    skillMarkdown({ description: "Use when hallmark", name: "hallmark" }),
    "utf8"
  );
  await writeFile(join(root, "docs/features.md"), catalog, "utf8");
  await writeFile(
    join(root, "site/skill-docs/alpha.md"),
    "## 何ができるか\n\nalpha の解説です。`--collect`\n\n## つまずいたら\n\n確認してください。\n",
    "utf8"
  );
  await writeFile(
    join(root, "site/skill-docs/beta.md"),
    "## 何ができるか\n\nbeta の解説です。\n\n## つまずいたら\n\n確認してください。\n",
    "utf8"
  );
  return root;
};

test("frontmatter とリファレンス用の公開節だけを抽出する", () => {
  const parsed = parseSkillMarkdown(
    skillMarkdown({ prerequisites: "\n## 前提\n\nrequired\n\n" }),
    "alpha"
  );

  assert.equal(parsed.name, "alpha");
  assert.equal(parsed.description, "Use when 「テストして」「試して」。--collect の後続は /beta");
  assert.deepEqual(parsed.triggerPhrases, ["テストして", "試して"]);
  assert.equal(parsed.prerequisites, "required");
  assert.equal(parsed.artifacts, "- `output.md`");
  assert.equal(parsed.apiCalls, undefined);
  assert.match(parsed.workflow, /後工程/);
  assert.doesNotMatch(parsed.workflow, /INTERNAL INSTRUCTION/);
});

test("二重鉤括弧の発動フレーズも抽出する", () => {
  const parsed = parseSkillMarkdown(
    skillMarkdown({ description: "Use when 『準備』「配信準備」で発動" }),
    "alpha"
  );

  assert.deepEqual(parsed.triggerPhrases, ["準備", "配信準備"]);
});

test("description 欠損は該当 skill 名を示して拒否する", () => {
  const markdown = skillMarkdown().replace(/^description:.*\n/mu, "");
  assert.throws(
    () => parseSkillMarkdown(markdown, "alpha"),
    /alpha.*description/i
  );
});

test("必須の成果物節がない skill を拒否する", () => {
  const markdown = skillMarkdown().replace(/## 成果物\n[\s\S]*?(?=## Task)/u, "");
  assert.throws(() => parseSkillMarkdown(markdown, "alpha"), /alpha.*成果物/i);
});

test("features のカテゴリと skill 順を抽出する", () => {
  assert.deepEqual(parseSkillCategories(catalog), [
    { label: "category one", skills: ["alpha"] },
    { label: "category two", skills: ["beta"] },
  ]);
});

test("骨格ページのリード文とリファレンスを生成する", async () => {
  const repositoryRoot = await createRepository();
  const source = createSkillPageSource({ repositoryRoot });
  const result = await source.load();

  assert.equal(result.entries.length, 3);
  assert.deepEqual(
    result.entries.map((entry) => entry.slug),
    ["/skills", "/skills/alpha", "/skills/beta"]
  );
  assert(!result.entries.some((entry) => entry.slug === "/skills/hallmark"));
  const alpha = result.entries.find((entry) => entry.slug === "/skills/alpha");
  assert.match(alpha.body.text, /\[\/beta\]\(\/skills\/beta\)/);
  assert.match(alpha.body.text, /^Use when 「テストして」「試して」。`--collect`/mu);
  assert.match(alpha.body.text, /## リファレンス/);
  assert.match(alpha.body.text, /### 発動フレーズ\n\n- テストして\n- 試して/);
  assert.match(alpha.body.text, /### 前後工程/);
  assert.match(alpha.body.text, /### 成果物\n\n- `output\.md`/);
  assert.match(alpha.body.text, /### 前提\n\nalpha prerequisite/);
  assert.doesNotMatch(alpha.body.text, /Task|Gotchas|Subagent|INTERNAL/);
  const beta = result.entries.find((entry) => entry.slug === "/skills/beta");
  assert.doesNotMatch(beta.body.text, /### 前提/);
  assert.doesNotMatch(beta.body.text, /### 発動フレーズ/);
  assert.match(beta.body.text, /## リファレンス\n\n### 前後工程/);
});

test("sidebar route は生成されるページとだけ一致する", async () => {
  const repositoryRoot = await createRepository();
  await mkdir(join(repositoryRoot, ".claude/skills/wip"), { recursive: true });

  const routes = skillSidebarRoutes(repositoryRoot);
  const slugs = (await createSkillPageSource({ repositoryRoot }).load()).entries
    .map((entry) => entry.slug)
    .toSorted();

  assert.deepEqual(routes, ["/skills", "/skills/features", "/skills/alpha", "/skills/beta"]);
  assert.deepEqual(
    routes.filter((route) => route !== "/skills/features").toSorted(),
    slugs
  );
});

test("実リポジトリの sidebar route は生成ページ全件と一致する", async () => {
  const repositoryRoot = resolve(import.meta.dirname, "../..");
  const routes = skillSidebarRoutes(repositoryRoot);
  const slugs = (await createSkillPageSource({ repositoryRoot }).load()).entries
    .map((entry) => entry.slug)
    .toSorted();

  assert.deepEqual(
    routes.filter((route) => route !== "/skills/features").toSorted(),
    slugs
  );
});

test("想定 API call 数があるときだけリファレンスに掲載する", async () => {
  const repositoryRoot = await createRepository();
  await writeFile(
    join(repositoryRoot, ".claude/skills/alpha/SKILL.md"),
    skillMarkdown({ apiCalls: "\n## 想定 API call 数\n\n- 1 call\n" }),
    "utf8"
  );
  const result = await createSkillPageSource({ repositoryRoot }).load();
  const alpha = result.entries.find((entry) => entry.slug === "/skills/alpha");

  assert.match(alpha.body.text, /### 想定 API call 数\n\n- 1 call/);
});

test("大文字始まりのフラグもコードスパン化する", async () => {
  const repositoryRoot = await createRepository();
  await writeFile(
    join(repositoryRoot, ".claude/skills/alpha/SKILL.md"),
    skillMarkdown({ description: "Use when 「テストして」。--Dry-Run を使う" }),
    "utf8"
  );
  const result = await createSkillPageSource({ repositoryRoot }).load();
  const alpha = result.entries.find((entry) => entry.slug === "/skills/alpha");

  assert.match(alpha.body.text, /`--Dry-Run`/);
});

test("一覧と個別ページの先頭 H1 を title へ分離する", async () => {
  const repositoryRoot = await createRepository();
  const source = createSkillPageSource({ repositoryRoot });
  const result = await source.load();

  const index = result.entries.find((entry) => entry.slug === "/skills");
  const alpha = result.entries.find((entry) => entry.slug === "/skills/alpha");

  assert.equal(index.data.title, "発動条件から skill を使う");
  assert.match(index.body.text, /発動条件・前提・前後工程/);
  assert.match(index.body.text, /\[できることの 1 行要約から探す\]\(\/skills\/features\)/);
  assert.doesNotMatch(index.body.text, /^# /mu);
  assert.match(index.body.text, /^## category one$/mu);
  assert.match(index.raw, /^---\ntitle: "発動条件から skill を使う"\ntype: doc\n---\n\n/mu);
  assert.equal(alpha.data.title, "/alpha");
  assert.doesNotMatch(alpha.body.text, /^# /mu);
  assert.match(alpha.body.text, /^## リファレンス$/mu);
  assert.match(alpha.body.text, /^### 前提$/mu);
  assert.match(alpha.raw, /^---\ntitle: "\/alpha"\ntype: doc\n---\n\n/mu);
});

test("skill を追加して手書き解説を追加し忘れると拒否する", async () => {
  const repositoryRoot = await createRepository();
  const source = createSkillPageSource({ repositoryRoot });
  await mkdir(join(repositoryRoot, ".claude/skills/gamma"), { recursive: true });
  await writeFile(
    join(repositoryRoot, ".claude/skills/gamma/SKILL.md"),
    skillMarkdown({ description: "Use when gamma", name: "gamma" }),
    "utf8"
  );
  await assert.rejects(() => source.load(), /gamma.*handwritten/i);
});

test("対象 skill の手書き解説が欠落していると拒否する", async () => {
  const repositoryRoot = await createRepository();
  await rm(join(repositoryRoot, "site/skill-docs/alpha.md"));

  await assert.rejects(
    () => createSkillPageSource({ repositoryRoot }).load(),
    /alpha.*handwritten/i
  );
});

test("実リポジトリでは9カテゴリと配布対象skillだけを生成する", async () => {
  const repositoryRoot = resolve(import.meta.dirname, "../..");
  const source = createSkillPageSource({ repositoryRoot });
  const result = await source.load();
  const skillDirectories = (
    await readFile(join(repositoryRoot, "docs/features.md"), "utf8")
  ).match(/^\| \/[a-z0-9-]+ /gmu);

  assert.equal(result.entries.length, 20);
  assert.equal(skillDirectories?.length, 19);
  for (const entry of result.entries) {
    assert.doesNotMatch(
      entry.body.text,
      /### 発動フレーズ\n\s*(?:###|$)/u,
      `${entry.slug} が空の発動フレーズ節を出力している`
    );
  }
  const distrokid = result.entries.find(
    (entry) => entry.slug === "/skills/distrokid-helper"
  );
  assert.match(distrokid.body.text, /### 発動フレーズ\n\n- DistroKid 準備\n/);
  const video = result.entries.find((entry) => entry.slug === "/skills/video");
  assert.doesNotMatch(video.body.text, /### 発動フレーズ/);
  assert.equal(parseSkillCategories(await readFile(join(repositoryRoot, "docs/features.md"), "utf8")).length, 9);
  assert.doesNotMatch(result.entries[0].body.text, /## 未分類/);
  const music = result.entries.find((entry) => entry.slug === "/skills/music");
  assert.match(music.body.text, /## 何ができるか[\s\S]*## つまずいたら[\s\S]*## リファレンス/u);
  assert.match(music.body.text, /`\/music --prompt`/u);
  assert.match(music.body.text, /^\/music {13}# 状態判定つき一括実行/mu);
  assert.doesNotMatch(music.body.text, /`\[\/music\]/u);
  for (const skillName of [
    "analytics",
    "audit",
    "channel-research",
    "channel-strategy",
  ]) {
    const skill = result.entries.find(
      (entry) => entry.slug === `/skills/${skillName}`
    );
    assert.match(
      skill.body.text,
      /## 何ができるか[\s\S]*## つまずいたら[\s\S]*## リファレンス/u
    );
  }
});

test("production build は一覧と19個の個別ページを公開する", async () => {
  const siteRoot = resolve(import.meta.dirname, "..");
  const index = await readFile(join(siteRoot, "dist/skills/index.html"), "utf8");
  const thumbnail = await readFile(
    join(siteRoot, "dist/skills/thumbnail/index.html"),
    "utf8"
  );
  const music = await readFile(join(siteRoot, "dist/skills/music/index.html"), "utf8");

  assert.match(index, /19 個の skill/);
  assert.match(index, /href="\/skills\/wf-new"/);
  assert.doesNotMatch(index, /href="\/skills\/masterup"/);
  assert.doesNotMatch(index, /href="\/skills\/flop-analysis"/);
  assert.doesNotMatch(index, /href="\/skills\/channel-status"/);
  assert.doesNotMatch(index, /href="\/skills\/(?:automation-release|hallmark|shadcn)"/);
  assert.equal((index.match(/<h1\b/g) ?? []).length, 1);
  assert.match(index, /<h1[^>]*>発動条件から skill を使う<\/h1>/);
  assert.match(index, /href="\/skills\/features"/);
  assert.match(thumbnail, /--compare/);
  assert.match(thumbnail, /--test/);
  assert.match(thumbnail, /--iterate/);
  assert.match(thumbnail, /--loop/);
  assert.match(music, /<code>--master<\/code>/);
  assert.doesNotMatch(index, /href="\/skills\/thumbnail-compare"/);
  assert.doesNotMatch(index, /href="\/skills\/thumbnail-test"/);
  assert.doesNotMatch(index, /href="\/skills\/thumbnail-iterate"/);
  assert.doesNotMatch(index, /href="\/skills\/loop-video"/);
  assert.equal((thumbnail.match(/<h1\b/g) ?? []).length, 1);
  assert.match(thumbnail, /<h1[^>]*>\/thumbnail<\/h1>/);
  assert.match(thumbnail, /<h2[^>]*>.*?リファレンス.*?<\/h2>/);
  assert.match(thumbnail, /<h3[^>]*>.*?前提.*?<\/h3>/);
  assert.doesNotMatch(thumbnail, /完了条件/);
  assert.doesNotMatch(thumbnail, /Subagent Contract|run_in_background|Gotchas/);
});

test("手書き解説をリード文とリファレンスの間に合成する", async () => {
  const repositoryRoot = await createRepository();
  await mkdir(join(repositoryRoot, "site/skill-docs"), { recursive: true });
  await writeFile(
    join(repositoryRoot, "site/skill-docs/alpha.md"),
    "## 何ができるか\n\n手書きの説明です。`--collect`\n\n## 試したいとき\n\n例です。\n\n## つまずいたら\n\n確認してください。\n",
    "utf8"
  );

  const result = await createSkillPageSource({ repositoryRoot }).load();
  const alpha = result.entries.find((entry) => entry.slug === "/skills/alpha");
  assert.match(
    alpha.body.text,
    /Use when.*\n\n## 何ができるか[\s\S]*## つまずいたら[\s\S]*## リファレンス/u
  );
});

test("対応する skill ディレクトリがない手書きファイルを拒否する", async () => {
  const repositoryRoot = await createRepository();
  await mkdir(join(repositoryRoot, "site/skill-docs"), { recursive: true });
  await writeFile(
    join(repositoryRoot, "site/skill-docs/removed.md"),
    "## 何ができるか\n\n説明\n\n## つまずいたら\n\n確認\n",
    "utf8"
  );

  await assert.rejects(
    () => createSkillPageSource({ repositoryRoot }).load(),
    /removed.*skill directory/u
  );
});

test("配布対象外 skill の手書きファイルは理由を示して拒否する", async () => {
  const repositoryRoot = await createRepository();
  await mkdir(join(repositoryRoot, "site/skill-docs"), { recursive: true });
  await writeFile(
    join(repositoryRoot, "site/skill-docs/hallmark.md"),
    "## 何ができるか\n\n説明\n\n## つまずいたら\n\n確認\n",
    "utf8"
  );

  await assert.rejects(
    () => createSkillPageSource({ repositoryRoot }).load(),
    /hallmark.*excluded from distribution/u
  );
});

test("手書き解説の最小セクション契約を検証する", async () => {
  const repositoryRoot = await createRepository();
  await mkdir(join(repositoryRoot, "site/skill-docs"), { recursive: true });
  await writeFile(
    join(repositoryRoot, "site/skill-docs/alpha.md"),
    "## つまずいたら\n\n確認\n\n## 何ができるか\n\n説明\n",
    "utf8"
  );

  await assert.rejects(
    () => createSkillPageSource({ repositoryRoot }).load(),
    /alpha.*何ができるか.*つまずいたら/u
  );
});

test("手書き解説の見出し前に本文があるファイルを拒否する", async () => {
  const repositoryRoot = await createRepository();
  await mkdir(join(repositoryRoot, "site/skill-docs"), { recursive: true });
  await writeFile(
    join(repositoryRoot, "site/skill-docs/alpha.md"),
    "前置きの一文\n\n## 何ができるか\n\n説明\n\n## つまずいたら\n\n確認\n",
    "utf8"
  );

  await assert.rejects(
    () => createSkillPageSource({ repositoryRoot }).load(),
    /alpha.*何ができるか.*つまずいたら/u
  );
});

test("コードスパン内のフラグ付き記法とフェンス例をリンク化しない", async () => {
  const repositoryRoot = await createRepository();
  await mkdir(join(repositoryRoot, "site/skill-docs"), { recursive: true });
  await writeFile(
    join(repositoryRoot, "site/skill-docs/alpha.md"),
    [
      "## 何ができるか",
      "",
      "単体の `/beta` はリンクになります。/beta も同じです。",
      "フラグ付きの `/beta --collect` はそのまま残します。",
      "",
      "```",
      "/beta --collect  # フェンス内はコピペ用なので触らない",
      "/alpha",
      "```",
      "",
      "## つまずいたら",
      "",
      "確認してください。",
      "",
    ].join("\n"),
    "utf8"
  );

  const result = await createSkillPageSource({ repositoryRoot }).load();
  const alpha = result.entries.find((entry) => entry.slug === "/skills/alpha");

  assert.match(alpha.body.text, /単体の \[\/beta\]\(\/skills\/beta\) はリンク/u);
  assert.match(alpha.body.text, /\[\/beta\]\(\/skills\/beta\) も同じです/u);
  assert.match(alpha.body.text, /フラグ付きの `\/beta --collect` はそのまま/u);
  assert.match(
    alpha.body.text,
    /```\n\/beta --collect  # フェンス内はコピペ用なので触らない\n\/alpha\n```/u
  );
});

test("モード判定表の全フラグが手書き解説の code span に必要", async () => {
  const repositoryRoot = await createRepository();
  await writeFile(
    join(repositoryRoot, ".claude/skills/alpha/SKILL.md"),
    skillMarkdown().replace(
      "## Task",
      "## モード判定\n\n| mode | reference |\n|---|---|\n| `--collect` | collect.md |\n| `--report` | report.md |\n\n## Task"
    ),
    "utf8"
  );
  await mkdir(join(repositoryRoot, "site/skill-docs"), { recursive: true });
  await writeFile(
    join(repositoryRoot, "site/skill-docs/alpha.md"),
    "## 何ができるか\n\n`--collect` を実行します。\n\n## つまずいたら\n\n確認\n",
    "utf8"
  );

  await assert.rejects(
    () => createSkillPageSource({ repositoryRoot }).load(),
    /alpha.*`--report`/u
  );
});
