import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import {
  operatorDocMap,
  operatorDocRedirects,
  upgradeGuideRoutes,
} from "../operator-doc-source.ts";
import {
  groupReleasesByScale,
  releaseScaleLabels,
  scaleFromVersion,
} from "../release-scale.ts";
import {
  firstReleaseRoute,
  releaseRedirects,
  releaseSidebarGroups,
} from "../release-sidebar.ts";
import { WORKFLOW_SKILL_GROUPS } from "../skill-page-source.ts";

const readIndex = () => readFile(new URL("../dist/index.html", import.meta.url), "utf8");
const readRelease = (version) =>
  readFile(new URL(`../dist/releases/${version}/index.html`, import.meta.url), "utf8");
const readOperatorDoc = (route) =>
  readFile(new URL(`../dist${route}/index.html`, import.meta.url), "utf8");
const releaseNotesDirectory = fileURLToPath(
  new URL("../../docs/release-notes", import.meta.url)
);
const execFileAsync = promisify(execFile);
const operatorSections = [
  {
    label: "はじめる",
    routes: [
      "/getting-started/tool-setup",
      "/getting-started/oauth-setup",
      "/getting-started/oauth-scopes",
      "/getting-started/chrome-extension-install-guide",
    ],
    section: "getting-started",
  },
  {
    label: "使う",
    routes: [
      "/skills/features",
      "/guides/workflow-cheatsheet",
      "/releases/workspace-migration",
      "/guides/dashboard",
      "/guides/cloud-execution",
      "/guides/live-chat-reply",
      "/guides/audio-studio",
      "/guides/review-viewers",
      "/guides/live-streaming",
      "/guides/streaming-healthcheck",
      "/guides/ambient-layers",
      "/guides/scheduled-publish",
      "/guides/localizations",
      "/guides/distrokid",
    ],
    section: "use",
  },
];
const operatorRoutes = operatorSections.flatMap(({ routes }) => routes);
/** navigation と同じ導出を使い、map への追加が sidebar 未掲載のまま通らないようにする。 */
const updateRoutes = [
  "/releases/high-cpm-locales",
  ...upgradeGuideRoutes(operatorDocMap),
];
const publicOperatorRoutes = [...operatorRoutes, ...updateRoutes];
/** 公開 route に、navigation から除外される /onboarding を足した生成 route 総数。 */
const generatedRouteCount = publicOperatorRoutes.length + 1;

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
    if (/<meta http-equiv="refresh"/u.test(html)) continue;
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

test("トップページは日本語検索と読者タスク別4入口を表示する", async () => {
  const html = await readIndex();
  const source = await readFile(new URL("../pages/index.astro", import.meta.url), "utf8");
  const cards = [...html.matchAll(/class="home-task-card" href="([^"]+)"[^>]*>[\s\S]*?<h2>([^<]+)<\/h2>/g)].map(
    (match) => ({ href: match[1], label: match[2] })
  );

  assert.match(html, /<main class="home-shell">/);
  assert.match(html, /<h1>何をしたいですか？<\/h1>/);
  assert.match(html, /<button[^>]*data-home-search[^>]*>[\s\S]*?ドキュメントを検索/);
  assert.match(source, /querySelector<HTMLButtonElement>\("\[data-blume-search-open\]"\)/);
  assert.deepEqual(cards, [
    { href: "/getting-started/tool-setup", label: "はじめる" },
    { href: "/guides/workflow-cheatsheet", label: "ガイド" },
    { href: "/skills", label: "スキル" },
    { href: "/releases/v5.7.0", label: "アップデート" },
  ]);
});

test("読者タスク別4タブは route prefix ごとに sidebar を切り替える", async () => {
  const sections = [
    {
      label: "はじめる",
      route: "/getting-started/tool-setup",
      tabHref: "/getting-started/tool-setup",
      sidebarRoutes: [
        "/getting-started/tool-setup",
        "/getting-started/oauth-setup",
        "/getting-started/oauth-scopes",
        "/getting-started/chrome-extension-install-guide",
      ],
    },
    {
      label: "ガイド",
      route: "/guides/workflow-cheatsheet",
      tabHref: "/guides/workflow-cheatsheet",
      sidebarRoutes: operatorRoutes.filter((route) => route.startsWith("/guides/")),
    },
    {
      label: "スキル",
      route: "/skills",
      tabHref: "/skills",
      sidebarRoutes: ["/skills", "/skills/analytics", "/skills/features"],
    },
    {
      label: "アップデート",
      route: "/releases/v5.6.0",
      tabHref: "/releases/v5.7.0",
      sidebarRoutes: [
        "/releases/v5.6.0",
        "/releases/ext-v0.3.0",
        "/releases/workspace-migration",
        ...updateRoutes,
      ],
    },
  ];

  for (const section of sections) {
    const html = await readOperatorDoc(section.route);
    const sidebar = html.match(/<nav data-blume-nav-tree>([\s\S]*?)<\/nav>/)?.[1] ?? "";
    const header = html.match(/<header\b[^>]*data-blume-header[^>]*>([\s\S]*?)<\/header>/)?.[1] ?? "";
    const tabs = header.match(/<nav aria-label="Sections"[^>]*>([\s\S]*?)<\/nav>/)?.[1] ?? "";

    for (const { label } of sections) {
      assert.match(tabs, new RegExp(`>${label}<`));
    }
    assert.match(tabs, new RegExp(`aria-current="page"[^>]*>\\s*${section.label}<`));
    assert.match(
      tabs,
      new RegExp(`href="${section.tabHref}"[^>]*>\\s*${section.label}<`)
    );
    for (const route of section.sidebarRoutes) {
      assert.equal(hrefsWithin(sidebar).filter((href) => href === route).length, 1);
    }
    const otherRoutes = sections
      .filter((candidate) => candidate !== section)
      .flatMap(({ sidebarRoutes }) => sidebarRoutes);
    assert.equal(otherRoutes.some((route) => hrefsWithin(sidebar).includes(route)), false);
  }
});

test("ガイド sidebar は読者タスク別5群で全ページを一度ずつ案内する", async () => {
  const html = await readOperatorDoc("/guides/workflow-cheatsheet");
  const sidebar = html.match(/<nav data-blume-nav-tree>([\s\S]*?)<\/nav>/)?.[1] ?? "";
  const labels = [
    "日々の制作",
    "公開を広げる",
    "ライブ配信",
    "視聴者と関わる",
    "手元ツール",
  ];

  assert.deepEqual(
    labels.map((label) => sidebar.indexOf(`>${label}<`)),
    labels.map((label) => sidebar.indexOf(`>${label}<`)).toSorted((a, b) => a - b)
  );
  for (const label of labels) assert.match(sidebar, new RegExp(`>${label}<`));
  assert.doesNotMatch(sidebar, />実験的機能<|>こんなこともできる！</);
  assert.equal(hrefsWithin(sidebar).filter((href) => href === "/guides/streaming-healthcheck").length, 1);
});

test("スキル sidebar は workflow 順8群で19 skill と検索入口を案内する", async () => {
  const html = await readOperatorDoc("/skills");
  const sidebar = html.match(/<nav data-blume-nav-tree>([\s\S]*?)<\/nav>/)?.[1] ?? "";
  const labels = WORKFLOW_SKILL_GROUPS.map(({ label }) => label);
  const skillHrefs = hrefsWithin(sidebar).filter(
    (href) => href.startsWith("/skills/") && href !== "/skills/features"
  );

  for (const label of labels) assert.match(sidebar, new RegExp(`>${label}<`));
  assert.equal(skillHrefs.length, 19);
  assert.equal(new Set(skillHrefs).size, 19);
  assert.match(sidebar, />できることから探す<[^]*href="\/skills"/);
  assert.equal(hrefsWithin(sidebar).filter((href) => href === "/skills/features").length, 1);
});

test("実験的機能の各ガイドは冒頭で利用上の注意を示す", async () => {
  for (const route of [
    "/guides/dashboard",
    "/guides/cloud-execution",
    "/guides/live-chat-reply",
    "/guides/audio-studio",
    "/guides/review-viewers",
  ]) {
    const html = await readOperatorDoc(route);
    const article = html.match(/<article\b[^>]*>([\s\S]*?)<\/article>/)?.[1] ?? "";
    assert.match(article.split("<h2", 1)[0], /実験的機能/);
  }
});

test(`onboarding は直接描画だけを維持し、公開operator docs ${publicOperatorRoutes.length}件だけを検索へ載せる`, async () => {
  const search = JSON.parse(
    await readFile(new URL("../dist/blume-search.json", import.meta.url), "utf8")
  );
  const searchRoutes = search.map(({ route }) => route);

  for (const route of publicOperatorRoutes) {
    const html = await readOperatorDoc(route);
    assert.match(html, /<article\b/);
    assert.equal(searchRoutes.filter((candidate) => candidate === route).length, 1);
  }

  const onboarding = await readOperatorDoc("/getting-started/onboarding");
  assert.match(onboarding, /<article\b/);
  assert.match(
    onboarding,
    /<meta(?=[^>]*name="robots")(?=[^>]*content="noindex")[^>]*>/i
  );
  assert.equal(searchRoutes.includes("/getting-started/onboarding"), false);

  const features = await readOperatorDoc("/skills/features");
  const toolSetup = await readOperatorDoc("/getting-started/tool-setup");
  const oauth = await readOperatorDoc("/getting-started/oauth-setup");
  assert.match(features, /href="\/guides\/workflow-cheatsheet"/);
  assert.match(features, /href="\/skills"/);
  assert.match(onboarding, /href="\/getting-started\/oauth-setup"/);
  assert.match(toolSetup, /href="\/getting-started\/oauth-setup"/);
  assert.match(oauth, /href="\/getting-started\/tool-setup"/);
  assert.match(oauth, /href="\/getting-started\/onboarding"/);
  assert.match(
    onboarding,
    /href="https:\/\/github\.com\/daiki-beppu\/youtube-automation\/blob\/main\/docs\/migration\/python-to-tayk\.md"/
  );
});

test(`operator docs の${generatedRouteCount} route は原本の先頭見出しを唯一の H1 として描画する`, async () => {
  const expectedTitles = new Map([
    ["/getting-started/onboarding", "Onboarding"],
    ["/getting-started/tool-setup", "ツール導入"],
    [
      "/getting-started/oauth-setup",
      "GCP / YouTube API セットアップ",
    ],
    ["/getting-started/oauth-scopes", "YouTube 権限を安全に使い分ける"],
    ["/skills/features", "できることから skill を探す"],
    ["/guides/workflow-cheatsheet", "workflow チートシート"],
    ["/getting-started/chrome-extension-install-guide", "Chrome 拡張インストールガイド"],
    ["/guides/dashboard", "Analytics dashboard"],
    [
      "/releases/workspace-migration",
      "単一チャンネル repository から workspace への移行",
    ],
    ["/guides/cloud-execution", "クラウドでの実行"],
    ["/guides/live-streaming", "24時間ライブ配信を始める"],
    ["/guides/streaming-healthcheck", "ライブ配信の稼働状態を確認する"],
    ["/guides/live-chat-reply", "ライブチャット自動返信を試す"],
    ["/guides/ambient-layers", "環境音レイヤーを重ねる"],
    ["/guides/scheduled-publish", "公開日時を決めて予約公開する"],
    ["/guides/localizations", "タイトルと概要欄を多言語化する"],
    ["/guides/distrokid", "楽曲を DistroKid 配信向けに準備する"],
    ["/guides/audio-studio", "Audio Studio で音を調整する"],
    ["/guides/review-viewers", "review 用 HTML で音源と動画を確認する"],
    ["/releases/high-cpm-locales", "high-CPM ローカライズ移行ガイド"],
    ["/releases/upgrades/v5.4.0", "v5.4.0 アップグレードガイド"],
    ["/releases/upgrades/v5.5.0", "v5.5.0 アップグレードガイド"],
    ["/releases/upgrades/v5.5.1", "v5.5.1 アップグレードガイド"],
  ]);

  assert.equal(expectedTitles.size, generatedRouteCount);
  for (const [route, expectedTitle] of expectedTitles) {
    const html = await readOperatorDoc(route);
    const headings = [...html.matchAll(/<h1(?:\s[^>]*)?>([^<]+)<\/h1>/g)].map(
      (match) => match[1]
    );

    assert.deepEqual(headings, [expectedTitle]);
    if (route === "/getting-started/onboarding") {
      assert.match(html, /<h2 id="1-このリポジトリは何か">/);
    }
  }
});

test("AI出力はonboardingだけを除外し、直接取得用Markdown生成は維持する", async () => {
  const llms = await readFile(new URL("../dist/llms.txt", import.meta.url), "utf8");
  const llmsFull = await readFile(new URL("../dist/llms-full.txt", import.meta.url), "utf8");

  assert.doesNotMatch(llms, /\[Onboarding\]\(\/getting-started\/onboarding\)/i);
  assert.doesNotMatch(llmsFull, /^# Onboarding$/mu);
  assert.doesNotMatch(llmsFull, /## 1\. このリポジトリは何か/);
  for (const route of publicOperatorRoutes) {
    assert.match(llms, new RegExp(route.replaceAll("/", "\\/")));
    assert.match(llmsFull, new RegExp(`^Source: ${route}$`, "mu"));
  }
  for (const extension of ["md", "mdx"]) {
    const markdown = await readFile(
      new URL(`../dist/getting-started/onboarding.${extension}`, import.meta.url),
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
    assert.doesNotMatch(sitemap, /\/getting-started\/onboarding\/?(?:<|$)/);
    for (const route of publicOperatorRoutes) {
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

test("トップページは最新リリース1件をハイライトする", async () => {
  const html = await readIndex();
  const notes = await releaseNotes();
  const latest = notes.toSorted(
    (left, right) => right.released_at.getTime() - left.released_at.getTime()
  )[0];
  const highlight = sectionByAttribute(html, "data-home-section", "latest-release");

  assert.equal((highlight.match(/class="release-card"/g) ?? []).length, 1);
  assert.match(highlight, new RegExp(`href="/releases/${latest.version}"`));
  assert.match(highlight, new RegExp(`<h2>${latest.version}</h2>`));
  assert.match(highlight, new RegExp(latest.title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
});

test("対応形式でない version は version を示して拒否する", () => {
  const invalidVersions = ["5.6.0", "v5.6", "plugin-v1.0.0", "v1.0.0-beta"];

  for (const version of invalidVersions) {
    assert.throws(() => scaleFromVersion(version), new RegExp(version.replaceAll(".", "\\.")));
  }
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

const releaseNotes = async () => {
  const files = (await readdir(releaseNotesDirectory)).filter((file) =>
    file.endsWith(".md")
  );
  return Promise.all(
    files.map(async (file) => {
      const source = await readFile(join(releaseNotesDirectory, file), "utf8");
      const title = source.match(/^title:\s*"?(?<title>.+?)"?$/mu)?.groups.title;
      const kind = source.match(/^kind:\s*(?<kind>main|extension)$/mu)?.groups.kind;
      const releasedAt = source.match(/^released_at:\s*(?<date>\d{4}-\d{2}-\d{2})$/mu)
        ?.groups.date;
      assert.ok(title, `release note has no title: ${file}`);
      assert.ok(kind, `release note has no kind: ${file}`);
      assert.ok(releasedAt, `release note has no released_at: ${file}`);
      return {
        kind,
        released_at: new Date(`${releasedAt}T00:00:00.000Z`),
        title,
        version: file.replace(/\.md$/u, ""),
      };
    })
  );
};

const writeReleaseNotes = async (directory, releases) =>
  Promise.all(
    releases.map(({ file, kind, released_at, version }) =>
      writeFile(
        join(directory, file ?? `${version}.md`),
        [
          "---",
          `title: "${version}"`,
          `version: ${version}`,
          `released_at: ${released_at}`,
          `kind: ${kind}`,
          'summary: "テスト用のリリース"',
          "sidebar:",
          "  order: -1",
          "---",
          "",
        ].join("\n")
      )
    )
  );

test("sidebar の release 節を実ファイル群から導出し、節内を公開日の降順にする", async () => {
  const directory = await mkdtemp(join(tmpdir(), "release-sidebar-"));
  await writeReleaseNotes(directory, [
    { kind: "main", released_at: "2026-07-31", version: "v5.6.0" },
    { kind: "main", released_at: "2026-08-29", version: "v5.7.0" },
    { kind: "main", released_at: "2026-07-10", version: "v5.5.17" },
    { kind: "extension", released_at: "2026-07-31", version: "ext-v0.3.0" },
  ]);

  assert.deepEqual(releaseSidebarGroups(directory), [
    {
      items: ["/releases/v5.7.0", "/releases/v5.6.0"],
      label: `本体｜${releaseScaleLabels.major}`,
    },
    { items: ["/releases/v5.5.17"], label: `本体｜${releaseScaleLabels.minor}` },
    {
      items: ["/releases/ext-v0.3.0"],
      label: `Chrome 拡張｜${releaseScaleLabels.major}`,
    },
  ]);
});

test("全リリースの旧 URL を /releases/ 配下へ恒久リダイレクトする", async () => {
  const directory = await mkdtemp(join(tmpdir(), "release-redirects-"));
  await writeReleaseNotes(directory, [
    { kind: "main", released_at: "2026-08-29", version: "v5.7.0" },
    { kind: "extension", released_at: "2026-07-31", version: "ext-v0.3.0" },
  ]);

  assert.deepEqual(releaseRedirects(directory), [
    { from: "/ext-v0.3.0", status: 301, to: "/releases/ext-v0.3.0" },
    { from: "/v5.7.0", status: 301, to: "/releases/v5.7.0" },
  ]);
});

test("production build は旧 URL 全件の Cloudflare Pages redirect を出力する", async () => {
  const redirects = await readFile(new URL("../dist/_redirects", import.meta.url), "utf8");
  const expected = [
    ...(await releaseNotes()).map(
      ({ version }) => `/${version} /releases/${version} 301`
    ),
    ...operatorDocRedirects(operatorDocMap).map(
      ({ from, to }) => `${from} ${to} 301`
    ),
  ].toSorted();

  assert.deepEqual(redirects.trim().split("\n").toSorted(), expected);
});

test("タブ導入前の operator doc URL は production build で新 route へ転送する", async () => {
  const redirects = await readFile(new URL("../dist/_redirects", import.meta.url), "utf8");

  for (const route of ["/tool-setup", "/features", "/dashboard", "/onboarding"]) {
    const to = operatorDocMap.find(
      (entry) => entry.legacyRoute === route
    )?.route;

    assert.ok(to, `${route} は operator doc map の legacy route である`);
    assert.match(redirects, new RegExp(`^${route} ${to} 301$`, "mu"));
  }
});

test("リリースノートが 1 件も無い構成はタブの既定リンク先を解決できず落ちる", () => {
  assert.throws(() => firstReleaseRoute([]), /no release note/iu);
  assert.equal(
    firstReleaseRoute([{ items: ["/releases/v5.7.0"], label: "本体｜大" }]),
    "/releases/v5.7.0"
  );
});

test("ファイル名と version が食い違う release note を path 付きで拒否する", async () => {
  const directory = await mkdtemp(join(tmpdir(), "release-sidebar-"));
  await writeReleaseNotes(directory, [
    { file: "v5.6.1.md", kind: "main", released_at: "2026-07-31", version: "v5.6.0" },
  ]);

  assert.throws(() => releaseSidebarGroups(directory), /v5\.6\.1\.md/u);
});

test("全詳細ページのサイドバーへ release 節を実ファイル群から反映する", async () => {
  const expectedGroups = releaseSidebarGroups(releaseNotesDirectory).map((group) => ({
    hrefs: [...group.items],
    label: group.label,
  }));
  const notes = await releaseNotes();

  assert.ok(notes.length > 0);
  for (const note of notes) {
    const html = await readRelease(note.version);
    const titles = [...html.matchAll(/<h1(?:\s[^>]*)?>([^<]+)<\/h1>/g)].map(
      (match) => match[1]
    );

    assert.equal(titles.filter((title) => title === note.title).length, 1);
    assert.match(html, /youtube-automation ドキュメント/);
    assert.deepEqual(sidebarGroups(html), expectedGroups);
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
