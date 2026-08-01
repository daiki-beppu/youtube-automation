import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { promisify } from "node:util";

const readIndex = () => readFile(new URL("../dist/index.html", import.meta.url), "utf8");
const execFileAsync = promisify(execFile);

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
