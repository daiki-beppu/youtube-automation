import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { promisify } from "node:util";

const readIndex = () => readFile(new URL("../dist/index.html", import.meta.url), "utf8");
const readRelease = (version) =>
  readFile(new URL(`../dist/${version}/index.html`, import.meta.url), "utf8");
const execFileAsync = promisify(execFile);

test("一覧は本体とChrome拡張に分かれ、それぞれ公開日の新しい順で表示する", async () => {
  const html = await readIndex();
  const section = (kind) =>
    html.match(new RegExp(`<section[^>]*data-release-kind="${kind}"[^>]*>([\\s\\S]*?)<\\/section>`))
      ?.[1] ?? "";
  const main = section("main");
  const extension = section("extension");
  const hrefs = (markup) =>
    [...markup.matchAll(/class="release-card" href="([^"]+)"/g)].map((match) => match[1]);

  assert.match(main, /<h2>本体<\/h2>/);
  assert.match(extension, /<h2>Chrome 拡張<\/h2>/);
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

test("詳細ページはタイトルを一度だけ表示し、サイドバーを種類別・新しい順に並べる", async () => {
  const html = await readRelease("v5.6.0");
  const titleMatches = html.match(/<h1(?:\s[^>]*)?>youtube-automation v5\.6\.0<\/h1>/g) ?? [];
  const sidebar = html.match(/<nav data-blume-nav-tree>([\s\S]*?)<\/nav>/)?.[1] ?? "";
  const hrefs = [...sidebar.matchAll(/href="(\/[^"#]+)"/g)].map((match) => match[1]);

  assert.equal(titleMatches.length, 1);
  assert.match(html, /youtube-automation ドキュメント/);
  assert.ok(sidebar.indexOf("本体") < sidebar.indexOf("Chrome 拡張"));
  assert.deepEqual(hrefs, ["/v5.6.0", "/v5.5.17", "/ext-v0.3.0", "/ext-v0.2.5"]);
});

test("アップデートコマンドをコピー可能なコードブロックで表示する", async () => {
  const main = await readRelease("v5.6.0");
  const extension = await readRelease("ext-v0.3.0");

  assert.match(main, /<code>\/automation-update\n?<\/code>/);
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
