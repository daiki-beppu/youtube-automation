import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";
import { promisify } from "node:util";
import {
  groupReleasesByScale,
  releaseScaleLabels,
  scaleFromVersion,
} from "../release-scale.ts";

const readIndex = () => readFile(new URL("../dist/index.html", import.meta.url), "utf8");
const readRelease = (version) =>
  readFile(new URL(`../dist/${version}/index.html`, import.meta.url), "utf8");
const readOperatorDoc = (route) =>
  readFile(new URL(`../dist${route}/index.html`, import.meta.url), "utf8");
const execFileAsync = promisify(execFile);
const operatorSections = [
  {
    label: "はじめる",
    routes: ["/tool-setup", "/oauth-setup", "/chrome-extension-install-guide"],
    section: "getting-started",
  },
  {
    label: "使う",
    routes: [
      "/features",
      "/workflow-cheatsheet",
      "/channel-workspace-migration",
      "/dashboard",
      "/cloud-execution",
      "/live-chat-reply",
      "/live-streaming",
    ],
    section: "use",
  },
];
const operatorRoutes = operatorSections.flatMap(({ routes }) => routes);
/** 公開 route に、navigation から除外される /onboarding を足した生成 route 総数。 */
const generatedRouteCount = operatorRoutes.length + 1;

const readStylesheetClosure = async (html) => {
  const inlineStyles = [...html.matchAll(/<style(?:\s[^>]*)?>([\s\S]*?)<\/style>/g)].map(
    (match) => match[1]
  );
  const linkedStyles = await Promise.all(
    [...html.matchAll(/<link[^>]+href=["']([^"']+\.css)["'][^>]*>/g)].map((match) =>
      readFile(new URL(`../dist${match[1]}`, import.meta.url), "utf8")
    )
  );
  return [...inlineStyles, ...linkedStyles].join("\n");
};

test("公式 DADS design tokens の exact dependency と CSS token surface を提供する", async () => {
  const sitePackage = JSON.parse(
    await readFile(new URL("../package.json", import.meta.url), "utf8")
  );
  const designTokensPackage = JSON.parse(
    await readFile(
      new URL(
        "../node_modules/@digital-go-jp/design-tokens/package.json",
        import.meta.url
      ),
      "utf8"
    )
  );
  const tokens = await readFile(
    new URL(
      "../node_modules/@digital-go-jp/design-tokens/dist/tokens-simple.css",
      import.meta.url
    ),
    "utf8"
  );

  assert.equal(sitePackage.dependencies["@digital-go-jp/design-tokens"], "2.0.1");
  assert.equal(designTokensPackage.version, "2.0.1");
  assert.match(tokens, /--color-key-/);
  assert.match(tokens, /--color-neutral-/);
  assert.match(tokens, /--color-semantic-/);
});

test("DADS key と neutral token を system mode の site 配色へ割り当てる", async () => {
  const config = await readFile(new URL("../blume.config.ts", import.meta.url), "utf8");
  const sourceCss = await readFile(
    new URL("../styles/release-notes.css", import.meta.url),
    "utf8"
  );
  const assetDirectory = new URL("../dist/_astro/", import.meta.url);
  const generatedCss = (
    await Promise.all(
      (await readdir(assetDirectory))
        .filter((name) => name.endsWith(".css"))
        .map((name) => readFile(new URL(name, assetDirectory), "utf8"))
    )
  ).join("\n");

  assert.match(
    sourceCss,
    /@import ["']@digital-go-jp\/design-tokens\/dist\/tokens-simple\.css["'];/
  );
  assert.match(
    config,
    /import dadsTokens from ["']@digital-go-jp\/design-tokens["']/
  );
  assert.match(
    config,
    /const lightAccent = dadsTokens\.Color\.Key\["800"\]\.\$value/
  );
  assert.match(
    config,
    /const darkAccent = dadsTokens\.Color\.Key\["400"\]\.\$value/
  );
  assert.match(
    config,
    /accent:\s*\{\s*light:\s*lightAccent,\s*dark:\s*darkAccent,?\s*\}/
  );
  assert.doesNotMatch(config, /#[0-9a-f]{3,8}\b/i);
  assert.match(config, /mode:\s*["']system["']/);
  assert.match(sourceCss, /--release-main:\s*var\(--color-key-800\)/);
  assert.match(
    sourceCss,
    /--release-extension:\s*var\(--color-neutral-solid-gray-700\)/
  );
  assert.match(sourceCss, /--release-border:\s*var\(--color-neutral-solid-gray-420\)/);
  assert.match(
    sourceCss,
    /:root\[data-theme=["']dark["']\][\s\S]*--release-main:\s*var\(--color-key-400\)[\s\S]*--release-extension:\s*var\(--color-neutral-solid-gray-300\)[\s\S]*--release-border:\s*var\(--color-neutral-solid-gray-600\)/
  );
  assert.match(
    sourceCss,
    /:root\[data-theme=["']dark["']\][\s\S]*--release-main-bg:\s*color-mix\(in srgb, var\(--color-key-400\) 8%, transparent\)/
  );
  assert.match(sourceCss, /color:\s*var\(--color-muted-foreground\)/);
  assert.match(sourceCss, /border:\s*1px solid var\(--release-border\)/);
  assert.match(
    sourceCss,
    /\.release-card:hover\s*\{[\s\S]*border-color:\s*color-mix\(in srgb, var\(--release-main\) 60%, transparent\)/
  );
  assert.doesNotMatch(sourceCss, /#[0-9a-f]{3,8}\b/i);
  assert.doesNotMatch(sourceCss, /#7c3aed|#0f766e|--color-text-muted/i);
  assert.doesNotMatch(
    sourceCss,
    /--release-(?:main|extension):[^;]*--color-semantic-(?:success|error|warning)/
  );
  assert.match(generatedCss, /--color-key-800/);
  assert.match(generatedCss, /--color-key-400/);
  assert.match(generatedCss, /--color-neutral-solid-gray-700/);
  assert.match(generatedCss, /--color-neutral-solid-gray-300/);
  assert.match(generatedCss, /--release-border:var\(--color-neutral-solid-gray-420\)/);
  assert.match(generatedCss, /--release-border:var\(--color-neutral-solid-gray-600\)/);
  assert.doesNotMatch(generatedCss, /#7c3aed|#0f766e/i);
});

test("全 Blume page の stylesheet closure で DADS accent を解決する", async () => {
  const designTokens = (await import("@digital-go-jp/design-tokens")).default;
  const lightAccent = designTokens.Color.Key["800"].$value;
  const darkAccent = designTokens.Color.Key["400"].$value;
  const distDirectory = new URL("../dist/", import.meta.url);
  const htmlPaths = (await readdir(distDirectory, { recursive: true })).filter((path) =>
    path.endsWith(".html")
  );

  assert.ok(htmlPaths.length > 1);
  for (const htmlPath of htmlPaths) {
    const html = await readFile(new URL(htmlPath, distDirectory), "utf8");
    const styles = await readStylesheetClosure(html);
    const accentReferences = [...styles.matchAll(/--blume-accent:\s*var\((--[^)]+)\)/g)];

    for (const [, variable] of accentReferences) {
      assert.match(styles, new RegExp(`${variable.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}:`));
    }
    assert.match(styles, new RegExp(`--blume-accent:\\s*${lightAccent}`));
    assert.match(styles, new RegExp(`--blume-accent:\\s*${darkAccent}`));
  }
});

const sectionByAttribute = (html, attribute, value) => {
  const opening = new RegExp(`<section\\b[^>]*\\b${attribute}="${value}"[^>]*>`).exec(html);
  assert.notEqual(opening, null, `${attribute}="${value}" の section が必要です`);

  const sectionTags = /<\/?section\b[^>]*>/g;
  const sectionMarkup = html.slice(opening.index);
  let depth = 0;

  for (const match of sectionMarkup.matchAll(sectionTags)) {
    depth += match[0].startsWith("</") ? -1 : 1;
    if (depth === 0) {
      return html.slice(opening.index, opening.index + match.index + match[0].length);
    }
  }

  throw new Error(`${attribute}="${value}" の section が閉じられていません`);
};

const hrefsWithin = (markup) =>
  [...markup.matchAll(/href="(\/[^"#?]*)"/g)].map((match) => match[1]);

test(`landing page は3区分を表示し、公開operator docs ${operatorRoutes.length}件だけへ1回ずつ到達できる`, async () => {
  const html = await readIndex();
  const sectionLabels = [
    ["getting-started", "はじめる"],
    ["use", "使う"],
    ["release-notes", "リリースノート"],
  ];

  for (const [section, label] of sectionLabels) {
    const markup = sectionByAttribute(html, "data-doc-section", section);
    assert.match(markup, new RegExp(`<h2>${label}</h2>`));
  }

  const operatorMarkup = operatorSections
    .map(({ section }) => sectionByAttribute(html, "data-doc-section", section))
    .join("\n");
  const operatorHrefs = hrefsWithin(operatorMarkup).filter((href) =>
    operatorRoutes.includes(href)
  );
  assert.deepEqual(operatorHrefs, operatorRoutes);
  assert.doesNotMatch(operatorMarkup, /href="\/onboarding(?:\/|"|#)/);
});

test("landing page はライブ配信を使う内の「こんなこともできる！」として表示する", async () => {
  const use = sectionByAttribute(await readIndex(), "data-doc-section", "use");
  const advanced = sectionByAttribute(use, "data-doc-group", "advanced");

  assert.match(advanced, /<h3>こんなこともできる！<\/h3>/);
  assert.deepEqual(hrefsWithin(advanced), ["/live-streaming"]);
  assert.equal(hrefsWithin(use).filter((href) => href === "/live-streaming").length, 1);
});

test("landing page は実験的機能を使う内の専用グループとして表示する", async () => {
  const use = sectionByAttribute(await readIndex(), "data-doc-section", "use");
  const experimental = sectionByAttribute(use, "data-doc-group", "experimental");

  assert.match(experimental, /<h3>実験的機能<\/h3>/);
  assert.deepEqual(hrefsWithin(experimental), [
    "/dashboard",
    "/cloud-execution",
    "/live-chat-reply",
  ]);
  assert.equal(hrefsWithin(use).filter((href) => href === "/dashboard").length, 1);
  assert.equal(hrefsWithin(use).filter((href) => href === "/cloud-execution").length, 1);
  assert.equal(hrefsWithin(use).filter((href) => href === "/live-chat-reply").length, 1);
});

test("全ページ共通 sidebar と tabs は operator 区分・release規模・exact route ownership を保つ", async () => {
  const pages = [await readRelease("v5.6.0"), await readOperatorDoc("/features")];

  for (const html of pages) {
    const sidebar = html.match(/<nav data-blume-nav-tree>([\s\S]*?)<\/nav>/)?.[1] ?? "";
    const header = html.match(/<header\b[^>]*data-blume-header[^>]*>([\s\S]*?)<\/header>/)?.[1] ?? "";
    const tabs = header.match(/<nav aria-label="Sections"[^>]*>([\s\S]*?)<\/nav>/)?.[1] ?? "";

    for (const { label } of operatorSections) {
      assert.match(sidebar, new RegExp(`>${label}<`));
      assert.match(tabs, new RegExp(`>${label}<`));
    }
    for (const label of [
      "本体｜大きいアップデート",
      "本体｜小さいアップデート",
      "Chrome 拡張｜大きいアップデート",
      "Chrome 拡張｜小さいアップデート",
    ]) {
      assert.match(sidebar, new RegExp(`>${label}<`));
    }
    assert.match(tabs, />リリースノート</);
    assert.deepEqual(
      [...tabs.matchAll(/href="([^"]+)"/g)].map((match) => match[1]),
      ["/#getting-started", "/#use", "/#release-notes"]
    );

    for (const route of operatorRoutes) {
      assert.equal(hrefsWithin(sidebar).filter((href) => href === route).length, 1);
    }
    assert.equal(hrefsWithin(sidebar).includes("/onboarding"), false);

    const experimentalLabel = sidebar.indexOf(">実験的機能<");
    const dashboard = sidebar.indexOf('href="/dashboard"');
    const cloudExecution = sidebar.indexOf('href="/cloud-execution"');
    const liveChatReply = sidebar.indexOf('href="/live-chat-reply"');
    assert.notEqual(experimentalLabel, -1);
    assert.ok(dashboard > experimentalLabel);
    assert.ok(cloudExecution > experimentalLabel);
    assert.ok(liveChatReply > experimentalLabel);
  }
});

test(`onboarding は直接描画だけを維持し、公開operator docs ${operatorRoutes.length}件だけを検索へ載せる`, async () => {
  const search = JSON.parse(
    await readFile(new URL("../dist/blume-search.json", import.meta.url), "utf8")
  );
  const searchRoutes = search.map(({ route }) => route);

  for (const route of operatorRoutes) {
    const html = await readOperatorDoc(route);
    assert.match(html, /<article\b/);
    assert.equal(searchRoutes.filter((candidate) => candidate === route).length, 1);
  }

  const onboarding = await readOperatorDoc("/onboarding");
  assert.match(onboarding, /<article\b/);
  assert.match(
    onboarding,
    /<meta(?=[^>]*name="robots")(?=[^>]*content="noindex")[^>]*>/i
  );
  assert.equal(searchRoutes.includes("/onboarding"), false);

  const features = await readOperatorDoc("/features");
  const toolSetup = await readOperatorDoc("/tool-setup");
  const oauth = await readOperatorDoc("/oauth-setup");
  assert.match(features, /href="\/workflow-cheatsheet"/);
  assert.match(onboarding, /href="\/oauth-setup"/);
  assert.match(toolSetup, /href="\/oauth-setup"/);
  assert.match(oauth, /href="\/tool-setup"/);
  assert.match(oauth, /href="\/onboarding"/);
  assert.match(
    onboarding,
    /href="https:\/\/github\.com\/daiki-beppu\/youtube-automation\/blob\/main\/docs\/migration\/python-to-tayk\.md"/
  );
});

test(`operator docs の${generatedRouteCount} route は原本の先頭見出しを唯一の H1 として描画する`, async () => {
  const expectedTitles = new Map([
    ["/onboarding", "Onboarding"],
    ["/tool-setup", "ツール導入"],
    [
      "/oauth-setup",
      "GCP / YouTube API セットアップ",
    ],
    ["/features", "全 skill カタログ"],
    ["/workflow-cheatsheet", "workflow チートシート"],
    ["/chrome-extension-install-guide", "Chrome 拡張インストールガイド"],
    ["/dashboard", "Analytics dashboard"],
    [
      "/channel-workspace-migration",
      "単一チャンネル repository から workspace への移行",
    ],
    ["/cloud-execution", "クラウドでの実行"],
    ["/live-streaming", "24時間ライブ配信を始める"],
    ["/live-chat-reply", "ライブチャット自動返信を試す"],
  ]);

  assert.equal(expectedTitles.size, generatedRouteCount);
  for (const [route, expectedTitle] of expectedTitles) {
    const html = await readOperatorDoc(route);
    const headings = [...html.matchAll(/<h1(?:\s[^>]*)?>([^<]+)<\/h1>/g)].map(
      (match) => match[1]
    );

    assert.deepEqual(headings, [expectedTitle]);
    if (route === "/onboarding") {
      assert.match(html, /<h2 id="1-このリポジトリは何か">/);
    }
  }
});

test("AI出力はonboardingだけを除外し、直接取得用Markdown生成は維持する", async () => {
  const llms = await readFile(new URL("../dist/llms.txt", import.meta.url), "utf8");
  const llmsFull = await readFile(new URL("../dist/llms-full.txt", import.meta.url), "utf8");

  assert.doesNotMatch(llms, /\[Onboarding\]\(\/onboarding\)/i);
  assert.doesNotMatch(llmsFull, /^# Onboarding$/mu);
  assert.doesNotMatch(llmsFull, /## 1\. このリポジトリは何か/);
  for (const route of operatorRoutes) {
    assert.match(llms, new RegExp(route.replaceAll("/", "\\/")));
    assert.match(llmsFull, new RegExp(`^Source: ${route}$`, "mu"));
  }
  for (const extension of ["md", "mdx"]) {
    const markdown = await readFile(
      new URL(`../dist/onboarding.${extension}`, import.meta.url),
      "utf8"
    );
    assert.match(markdown, /このリポジトリは何か/);
  }
});

test("sitemap が生成された場合だけ onboarding route を含めない", async () => {
  const generatedPaths = await readdir(new URL("../dist/", import.meta.url), {
    recursive: true,
  });
  const sitemapPaths = generatedPaths.filter((path) => /(?:^|\/)sitemap[^/]*\.xml$/u.test(path));

  for (const path of sitemapPaths) {
    const sitemap = await readFile(new URL(`../dist/${path}`, import.meta.url), "utf8");
    assert.doesNotMatch(sitemap, /\/onboarding\/?(?:<|$)/);
    for (const route of operatorRoutes) {
      assert.match(sitemap, new RegExp(`${route}/?`));
    }
  }
});

test("非掲載領域は route、navigation、landing、search に現れない", async () => {
  const distDirectory = new URL("../dist/", import.meta.url);
  const generatedPaths = await readdir(distDirectory, { recursive: true });
  const index = await readIndex();
  const release = await readRelease("v5.6.0");
  const search = JSON.parse(
    await readFile(new URL("../dist/blume-search.json", import.meta.url), "utf8")
  );

  assert.equal(generatedPaths.some((path) => path.startsWith("audits/")), false);
  assert.doesNotMatch(index, /href="\/audits(?:\/|"|#)/);
  assert.doesNotMatch(release, /href="\/audits(?:\/|"|#)/);
  assert.equal(search.some(({ route }) => route.startsWith("/audits")), false);
});

test("patch が 0 の version は major、それ以外は minor に分類する", () => {
  assert.equal(scaleFromVersion("v5.6.0"), "major");
  assert.equal(scaleFromVersion("ext-v0.3.0"), "major");
  assert.equal(scaleFromVersion("v5.5.17"), "minor");
  assert.equal(scaleFromVersion("ext-v0.2.5"), "minor");
});

test("release scale の表示名を一元的に提供する", () => {
  assert.deepEqual(releaseScaleLabels, {
    major: "大きいアップデート",
    minor: "小さいアップデート",
  });
});

test("release を規模別にまとめ、各 group 内を公開日の降順にする", () => {
  const releases = [
    { version: "v5.5.17", released_at: new Date("2026-01-02") },
    { version: "ext-v0.2.5", released_at: new Date("2026-02-02") },
    { version: "v5.6.0", released_at: new Date("2026-01-01") },
    { version: "ext-v0.3.0", released_at: new Date("2026-02-01") },
  ];

  const groups = groupReleasesByScale(releases);

  assert.deepEqual(
    groups.map((group) => ({
      scale: group.scale,
      label: group.label,
      versions: group.releases.map((release) => release.version),
    })),
    [
      {
        scale: "major",
        label: "大きいアップデート",
        versions: ["ext-v0.3.0", "v5.6.0"],
      },
      {
        scale: "minor",
        label: "小さいアップデート",
        versions: ["ext-v0.2.5", "v5.5.17"],
      },
    ]
  );
});

test("release がない規模の group は返さない", () => {
  const groups = groupReleasesByScale([
    { version: "v5.6.0", released_at: new Date("2026-01-01") },
  ]);

  assert.deepEqual(groups, [
    {
      scale: "major",
      label: "大きいアップデート",
      releases: [{ version: "v5.6.0", released_at: new Date("2026-01-01") }],
    },
  ]);
});

test("top page は kind の下に非空の更新規模 section を見出し階層付きで描画する", async () => {
  const html = await readIndex();

  for (const [kind, kindLabel] of [
    ["main", "本体"],
    ["extension", "Chrome 拡張"],
  ]) {
    const kindSection = sectionByAttribute(html, "data-release-kind", kind);
    const majorSection = sectionByAttribute(kindSection, "data-release-scale", "major");
    const minorSection = sectionByAttribute(kindSection, "data-release-scale", "minor");

    assert.match(kindSection, new RegExp(`<h3>${kindLabel}</h3>`));
    assert.equal([...kindSection.matchAll(/<section[^>]*data-release-scale=/g)].length, 2);
    assert.match(majorSection, /<h4>大きいアップデート<\/h4>/);
    assert.match(minorSection, /<h4>小さいアップデート<\/h4>/);
    assert.match(majorSection, /<ol[^>]*class="release-list"[^>]*>\s*<li>/);
    assert.match(minorSection, /<ol[^>]*class="release-list"[^>]*>\s*<li>/);
    assert.doesNotMatch(kindSection, /<section[^>]*data-release-scale[^>]*>\s*<h4>[^<]+<\/h4>\s*<ol[^>]*>\s*<\/ol>/);
  }
});

test("top page の kind × 更新規模 group は4 releaseの所属・日付・リンクを維持する", async () => {
  const html = await readIndex();
  const expectedGroups = [
    {
      kind: "main",
      scale: "major",
      version: "v5.6.0",
      date: "2026-07-31T00:00:00.000Z",
      href: "/v5.6.0",
    },
    {
      kind: "main",
      scale: "minor",
      version: "v5.5.17",
      date: "2026-07-10T00:00:00.000Z",
      href: "/v5.5.17",
    },
    {
      kind: "extension",
      scale: "major",
      version: "ext-v0.3.0",
      date: "2026-07-31T00:00:00.000Z",
      href: "/ext-v0.3.0",
    },
    {
      kind: "extension",
      scale: "minor",
      version: "ext-v0.2.5",
      date: "2026-07-10T00:00:00.000Z",
      href: "/ext-v0.2.5",
    },
  ];

  for (const expected of expectedGroups) {
    const kindSection = sectionByAttribute(html, "data-release-kind", expected.kind);
    const scaleSection = sectionByAttribute(
      kindSection,
      "data-release-scale",
      expected.scale
    );
    const hrefs = [...scaleSection.matchAll(/class="release-card" href="([^"]+)"/g)].map(
      (match) => match[1]
    );

    assert.deepEqual(hrefs, [expected.href]);
    assert.match(scaleSection, new RegExp(`<h5>${expected.version}</h5>`));
    assert.match(scaleSection, new RegExp(`<time datetime="${expected.date}">[^<]+</time>`));
    assert.match(
      scaleSection,
      new RegExp(`<span class="release-kind release-kind--${expected.kind}">`)
    );
    assert.match(scaleSection, /<p>[^<]+<\/p>/);
  }
});

test("対応形式でない version は version を示して拒否する", () => {
  const invalidVersions = ["5.6.0", "v5.6", "plugin-v1.0.0", "v1.0.0-beta"];

  for (const version of invalidVersions) {
    assert.throws(() => scaleFromVersion(version), new RegExp(version.replaceAll(".", "\\.")));
  }
});

test("一覧は本体とChrome拡張に分かれ、それぞれ公開日の新しい順で表示する", async () => {
  const html = await readIndex();
  const main = sectionByAttribute(html, "data-release-kind", "main");
  const extension = sectionByAttribute(html, "data-release-kind", "extension");
  const hrefs = (markup) =>
    [...markup.matchAll(/class="release-card" href="([^"]+)"/g)].map((match) => match[1]);

  assert.match(main, /<h3>本体<\/h3>/);
  assert.match(extension, /<h3>Chrome 拡張<\/h3>/);
  assert.deepEqual(hrefs(main), ["/v5.6.0", "/v5.5.17"]);
  assert.deepEqual(hrefs(extension), ["/ext-v0.3.0", "/ext-v0.2.5"]);
});

test("本体とChrome拡張を区別し、詳細ページへリンクする", async () => {
  const html = await readIndex();

  assert.match(html, /release-kind--main[^>]*>\s*本体/);
  assert.match(html, /release-kind--extension[^>]*>\s*Chrome 拡張/);
  assert.match(html, /href="\/v5\.6\.0\/?"/);
  assert.match(html, /href="\/ext-v0\.3\.0\/?"/);
});

const sidebarGroups = (html) => {
  const sidebar = html.match(/<nav data-blume-nav-tree>([\s\S]*?)<\/nav>/)?.[1] ?? "";
  const groupPattern = /<p\b[^>]*>\s*<span\b[^>]*>([^<]+)<\/span>\s*<\/p>\s*<div\b[^>]*>\s*<ul\b[^>]*>([\s\S]*?)<\/ul>/g;
  return [...sidebar.matchAll(groupPattern)]
    .filter((match) => match[1].includes("｜"))
    .map((match) => ({
      label: match[1],
      hrefs: [...match[2].matchAll(/href="(\/[^"#]+)"/g)].map((href) => href[1]),
    }));
};

test("全詳細ページのサイドバーを kind × 更新規模の4 flat groupで表示する", async () => {
  const expectedGroups = [
    { label: "本体｜大きいアップデート", hrefs: ["/v5.6.0"] },
    { label: "本体｜小さいアップデート", hrefs: ["/v5.5.17"] },
    { label: "Chrome 拡張｜大きいアップデート", hrefs: ["/ext-v0.3.0"] },
    { label: "Chrome 拡張｜小さいアップデート", hrefs: ["/ext-v0.2.5"] },
  ];
  const details = [
    { version: "v5.6.0", title: "youtube-automation v5.6.0" },
    { version: "v5.5.17", title: "youtube-automation v5.5.17" },
    { version: "ext-v0.3.0", title: "Chrome 拡張 ext-v0.3.0" },
    { version: "ext-v0.2.5", title: "Chrome 拡張 ext-v0.2.5" },
  ];

  for (const detail of details) {
    const html = await readRelease(detail.version);
    const titles = [...html.matchAll(/<h1(?:\s[^>]*)?>([^<]+)<\/h1>/g)].map(
      (match) => match[1]
    );
    const groups = sidebarGroups(html);

    assert.equal(titles.filter((title) => title === detail.title).length, 1);
    assert.match(html, /youtube-automation ドキュメント/);
    assert.deepEqual(groups, expectedGroups);
    assert.deepEqual(
      groups.flatMap((group) => group.hrefs),
      expectedGroups.flatMap((group) => group.hrefs)
    );
  }
});

test("アップデートコマンドをコピー可能なコードブロックで表示する", async () => {
  const main = await readRelease("v5.6.0");
  const extension = await readRelease("ext-v0.3.0");

  assert.match(main, /<code>\/automation --update\n?<\/code>/);
  assert.match(extension, /<code>\/ext-install\n?<\/code>/);
  assert.match(main, /data-blume-copy/);
  assert.match(extension, /data-blume-copy/);
});

test("必須キーがないリリースノートはキー名を示してビルドに失敗する", async () => {
  const fixture = new URL("fixtures/missing-summary", import.meta.url);
  const command = new URL("../node_modules/.bin/blume", import.meta.url);

  await assert.rejects(
    execFileAsync(command.pathname, ["build"], { cwd: fixture }),
    (error) => {
      assert.notEqual(error.code, 0);
      assert.match(`${error.stdout}\n${error.stderr}`, /summary/);
      return true;
    }
  );
});
