import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { promisify } from "node:util";

const readIndex = () => readFile(new URL("../dist/index.html", import.meta.url), "utf8");
const readRelease = (version) =>
  readFile(new URL(`../dist/${version}/index.html`, import.meta.url), "utf8");
const readTheme = () => readFile(new URL("../theme.css", import.meta.url), "utf8");
const execFileAsync = promisify(execFile);

const luminance = (hex) => {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)
    .map((channel) => Number.parseInt(channel, 16) / 255)
    .map((channel) =>
      channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
    );
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
};

const contrast = (foreground, background) => {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
};

const themeToken = (css, selector, name) => {
  const section = css.match(new RegExp(`${selector}\\s*\\{([\\s\\S]*?)\\}`))?.[1] ?? "";
  return section.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))?.[1];
};

test("一覧は公開日の新しい順で4件を表示する", async () => {
  const html = await readIndex();
  const hrefs = [...html.matchAll(/class="release-card" href="([^"]+)"/g)].map(
    (match) => match[1]
  );

  assert.deepEqual(hrefs, ["/v5.6.0", "/ext-v0.3.0", "/v5.5.17", "/ext-v0.2.5"]);
});

test("本体とChrome拡張を区別し、詳細ページへリンクする", async () => {
  const html = await readIndex();

  assert.match(html, /release-kind--main[^>]*>\s*本体/);
  assert.match(html, /release-kind--extension[^>]*>\s*Chrome 拡張/);
  assert.match(html, /href="\/v5\.6\.0\/?"/);
  assert.match(html, /href="\/ext-v0\.3\.0\/?"/);
});

test("詳細ページはタイトルを一度だけ表示し、サイドバーを新しい順に並べる", async () => {
  const html = await readRelease("v5.6.0");
  const titleMatches = html.match(/<h1(?:\s[^>]*)?>youtube-automation v5\.6\.0<\/h1>/g) ?? [];
  const sidebar = html.match(/<nav data-blume-nav-tree>([\s\S]*?)<\/nav>/)?.[1] ?? "";
  const hrefs = [...sidebar.matchAll(/href="(\/[^"#]+)"/g)].map((match) => match[1]);

  assert.equal(titleMatches.length, 1);
  assert.deepEqual(hrefs, ["/v5.6.0", "/ext-v0.3.0", "/v5.5.17", "/ext-v0.2.5"]);
});

test("アップデートコマンドをコピー可能なコードブロックで表示する", async () => {
  const main = await readRelease("v5.6.0");
  const extension = await readRelease("ext-v0.3.0");

  assert.match(main, /<code>\/automation-update\n?<\/code>/);
  assert.match(extension, /<code>\/ext-install\n?<\/code>/);
  assert.match(main, /data-blume-copy/);
  assert.match(extension, /data-blume-copy/);
});

test("配色トークンはライト・ダーク両方で本文コントラストを確保する", async () => {
  const css = await readTheme();
  const lightSelector = ":root";
  const darkSelector = String.raw`:root\[data-theme="dark"\]`;

  for (const selector of [lightSelector, darkSelector]) {
    const background = themeToken(css, selector, "blume-background");
    const foreground = themeToken(css, selector, "blume-foreground");
    const secondary = themeToken(css, selector, "blume-muted-foreground");
    const accent = themeToken(css, selector, "blume-accent");

    assert.ok(background && foreground && secondary && accent);
    assert.ok(contrast(foreground, background) >= 4.5);
    assert.ok(contrast(secondary, background) >= 4.5);
    assert.ok(contrast(accent, background) >= 4.5);
  }

  assert.match(css, /\.prose\s*\{[^}]*font-size:\s*1rem;[^}]*line-height:\s*1\.8;/s);
  assert.match(css, /\.prose\s+:where\(a\)/);
  assert.match(css, /text-decoration:\s*underline/);
  assert.match(css, /pre\.astro-code/);
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
