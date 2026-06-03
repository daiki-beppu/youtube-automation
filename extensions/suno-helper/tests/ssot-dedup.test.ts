// architect 指摘の再発防止:
//   - ssot-drift (ARCH-NEW-app-placeholder): popup の placeholder に DEFAULT_URL を
//     直書きすると、定数変更時に UI がドリフトする。契約値の直書きをソースで禁止する。
//   - dry-violation (ARCH-NEW-sleep-dup): content script が shared/dom の sleep を
//     再定義すると DRY 違反になる。一元化（shared/dom export）を機械担保する。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { DEFAULT_URL } from "../../shared/constants";
import { sleep } from "../../shared/dom";

const read = (rel: string): string => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), "utf8");

describe("ssot-drift: popup の placeholder は DEFAULT_URL を参照する", () => {
  const appSource = read("../components/App.tsx");

  it("Given App.tsx When 文字列を探す Then DEFAULT_URL の値を直書きしていない", () => {
    expect(appSource).not.toContain(DEFAULT_URL);
  });

  it("Given App.tsx When placeholder を読む Then 定数 DEFAULT_URL を参照する", () => {
    expect(appSource).toMatch(/import \{ DEFAULT_URL \} from "\.\.\/\.\.\/shared\/constants"/);
    expect(appSource).toMatch(/placeholder=\{DEFAULT_URL\}/);
  });
});

describe("dry-violation: sleep は shared/dom に一元化する", () => {
  const contentSource = read("../entrypoints/content.ts");

  it("Given shared/dom の sleep When 呼び出す Then 指定 ms 後に resolve する", async () => {
    await expect(sleep(0)).resolves.toBeUndefined();
  });

  it("Given content.ts When sleep の定義を探す Then 自前定義せず shared/dom から import する", () => {
    expect(contentSource).not.toMatch(/function sleep\b/);
    expect(contentSource).toMatch(/^\s*sleep,$/m);
  });
});
