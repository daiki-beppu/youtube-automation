import assert from "node:assert/strict";
import { mkdtemp, mkdir, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  createOperatorDocSource,
  operatorDocMap,
  operatorDocRedirects,
  rewriteFeatureSkillLinks,
  rewriteMarkdownLinks,
} from "../operator-doc-source.ts";

const expectedSources = [
  "ONBOARDING.md",
  "docs/tool-setup.md",
  "docs/oauth-setup.md",
  "docs/features.md",
  "docs/workflow-cheatsheet.md",
  "docs/chrome-extension-install-guide.md",
  "docs/dashboard.md",
  "docs/channel-workspace-migration.md",
  "docs/cloud-execution.md",
  "docs/live-streaming.md",
  "docs/live-chat-reply.md",
  "docs/ambient-layers.md",
  "docs/scheduled-publish.md",
  "docs/localizations.md",
  "docs/distrokid.md",
  "docs/audio-studio.md",
  "docs/review-viewers.md",
  "docs/migration/high-cpm-locales.md",
  "docs/upgrades/v5.4.0.md",
  "docs/upgrades/v5.5.0.md",
  "docs/upgrades/v5.5.1.md",
];

const createRepository = async (map = operatorDocMap) => {
  const repositoryRoot = await mkdtemp(join(tmpdir(), "operator-doc-source-"));
  await Promise.all(
    map.map(async ({ source }) => {
      const path = join(repositoryRoot, source);
      await mkdir(join(path, ".."), { recursive: true });
      await writeFile(path, `# ${source}\n`, "utf8");
    })
  );
  return repositoryRoot;
};

test(`operator document map は生成対象${expectedSources.length}件だけを明示列挙する`, () => {
  assert.deepEqual(
    operatorDocMap.map(({ source }) => source),
    expectedSources
  );
  assert.equal(
    new Set(operatorDocMap.map(({ route }) => route)).size,
    expectedSources.length
  );
});

test("追従ドキュメントをすべてアップデート tab 配下へ割り当てる", () => {
  const routes = new Map(operatorDocMap.map(({ route, source }) => [source, route]));

  assert.equal(
    routes.get("docs/channel-workspace-migration.md"),
    "/releases/workspace-migration"
  );
  assert.equal(
    routes.get("docs/migration/high-cpm-locales.md"),
    "/releases/high-cpm-locales"
  );
  for (const version of ["v5.4.0", "v5.5.0", "v5.5.1"]) {
    assert.equal(
      routes.get(`docs/upgrades/${version}.md`),
      `/releases/upgrades/${version}`
    );
  }
});

test("source は build ごとに原本を読み、安定 route と doc type を返す", async () => {
  const repositoryRoot = await createRepository();
  const source = createOperatorDocSource({ map: operatorDocMap, repositoryRoot });
  const onboarding = join(repositoryRoot, "ONBOARDING.md");

  await writeFile(onboarding, "# First\n\n## Details\n\nFirst body\n", "utf8");
  const first = await source.load();
  await writeFile(onboarding, "# Second\n\n## Details\n\nSecond body\n", "utf8");
  const second = await source.load();

  assert.equal(first.entries.length, expectedSources.length);
  assert.equal(first.entries[0].body.text, "## Details\n\nFirst body\n");
  assert.equal(second.entries[0].body.text, "## Details\n\nSecond body\n");
  assert.equal(first.entries[0].data.title, "First");
  assert.equal(second.entries[0].data.title, "Second");
  assert.equal(first.entries[0].slug, operatorDocMap[0].route);
  assert.equal(first.entries[0].data.type, "doc");
  assert.deepEqual(first.entries[0].data.ai, { exclude: true });
  assert.deepEqual(first.entries[0].data.search, { exclude: true });
  assert.equal(first.entries[0].data.noindex, true);
  for (const entry of first.entries.slice(1)) {
    assert.equal(entry.data.ai, undefined);
    assert.equal(entry.data.search, undefined);
    assert.equal(entry.data.noindex, undefined);
  }
  assert.equal(
    first.entries[0].raw,
    '---\ntitle: "First"\ntype: doc\nai:\n  exclude: true\nnoindex: true\nsearch:\n  exclude: true\nseo:\n  noindex: true\n---\n\n## Details\n\nFirst body\n'
  );
});

test("存在しない原本は解決対象を示して fail closed する", async () => {
  const repositoryRoot = await createRepository(operatorDocMap.slice(1));
  const source = createOperatorDocSource({ map: operatorDocMap, repositoryRoot });

  await assert.rejects(source.load(), /ONBOARDING\.md/);
});

test(`タブ導入前の flat route ${expectedSources.length}件を新 route へ恒久リダイレクトする`, () => {
  assert.deepEqual(
    operatorDocRedirects(operatorDocMap),
    operatorDocMap.map(({ legacyRoute, route }) => ({
      from: legacyRoute,
      status: 301,
      to: route,
    }))
  );
  assert.equal(
    new Set(operatorDocMap.map(({ legacyRoute }) => legacyRoute)).size,
    expectedSources.length
  );
});

test("legacy route を持たない doc は redirect を生成しない", () => {
  const map = [
    { source: "ONBOARDING.md", route: "/guides/setup" },
    { legacyRoute: "/old", source: "docs/oauth-setup.md", route: "/guides/new" },
  ];

  assert.deepEqual(operatorDocRedirects(map), [
    { from: "/old", status: 301, to: "/guides/new" },
  ]);
});

test("生成 route と衝突する legacy route は衝突先を示して拒否する", () => {
  const map = [
    { source: "ONBOARDING.md", route: "/guides/setup" },
    {
      legacyRoute: "/guides/setup",
      source: "docs/oauth-setup.md",
      route: "/guides/oauth",
    },
  ];

  assert.throws(() => operatorDocRedirects(map), /collides.*\/guides\/setup/i);
});

test("重複 legacy route は衝突した route を示して拒否する", () => {
  const map = [
    { legacyRoute: "/old", source: "ONBOARDING.md", route: "/guides/setup" },
    { legacyRoute: "/old", source: "docs/oauth-setup.md", route: "/guides/oauth" },
  ];

  assert.throws(
    () => operatorDocRedirects(map),
    /duplicate legacy route.*\/old/i
  );
});

test("重複 route は衝突した route を示して拒否する", () => {
  const map = [
    { source: "ONBOARDING.md", route: "/setup" },
    { source: "docs/oauth-setup.md", route: "/setup" },
  ];

  assert.throws(
    () => createOperatorDocSource({ map, repositoryRoot: "/tmp/repository" }),
    /duplicate route.*\/setup/i
  );
});

test("重複 source は衝突した source を示して拒否する", () => {
  const map = [
    { source: "ONBOARDING.md", route: "/setup" },
    { source: "ONBOARDING.md", route: "/another" },
  ];

  assert.throws(
    () => createOperatorDocSource({ map, repositoryRoot: "/tmp/repository" }),
    /duplicate source.*ONBOARDING\.md/i
  );
});

test("repository 外 path は解決対象を示して拒否する", () => {
  const map = [{ source: "../private.md", route: "/private" }];

  assert.throws(
    () => createOperatorDocSource({ map, repositoryRoot: "/tmp/repository" }),
    /repository.*\.\.\/private\.md/i
  );
});

test("repository 外を指す symlink は解決対象を示して拒否する", async () => {
  const repositoryRoot = await mkdtemp(join(tmpdir(), "operator-doc-source-"));
  const externalRoot = await mkdtemp(join(tmpdir(), "operator-doc-external-"));
  const external = join(externalRoot, "private.md");
  await writeFile(external, "# Private\n", "utf8");
  await symlink(external, join(repositoryRoot, "linked.md"));
  const source = createOperatorDocSource({
    map: [{ source: "linked.md", route: "/linked" }],
    repositoryRoot,
  });

  await assert.rejects(source.load(), /escapes repository.*linked\.md/i);
});

test("mapped Markdown link は site route と fragment へ書き換える", () => {
  const markdown =
    "[workflow](workflow-cheatsheet.md#再開) [setup](../ONBOARDING.md#install)";

  assert.equal(
    rewriteMarkdownLinks(markdown, "docs/features.md", operatorDocMap),
    "[workflow](/guides/workflow-cheatsheet#再開) [setup](/getting-started/onboarding#install)"
  );
});

test("map 外の repository-relative Markdown link は GitHub 原本へ書き換える", () => {
  const markdown = "[scope](oauth-scopes.md#read-only)";

  assert.equal(
    rewriteMarkdownLinks(markdown, "docs/oauth-setup.md", operatorDocMap),
    "[scope](https://github.com/daiki-beppu/youtube-automation/blob/main/docs/oauth-scopes.md#read-only)"
  );
});

test("anchor、絶対 URL、非 Markdown link は変更しない", () => {
  const markdown = [
    "[anchor](#local)",
    "[web](https://example.com/guide.md)",
    "[mail](mailto:operator@example.com)",
    "[config](../config/channel/meta.json)",
  ].join(" ");

  assert.equal(
    rewriteMarkdownLinks(markdown, "docs/features.md", operatorDocMap),
    markdown
  );
});

test("features の skill 行は個別ページへの導線にする", () => {
  const markdown = "| /thumbnail | CTR 最適化 |\n| /wf-new | 新規・一括企画 |\n";

  assert.equal(
    rewriteFeatureSkillLinks(markdown),
    "| [/thumbnail](/skills/thumbnail) | CTR 最適化 |\n" +
      "| [/wf-new](/skills/wf-new) | 新規・一括企画 |\n"
  );
});
