// architect 指摘の再発防止:
//   - ssot-drift (ARCH-NEW-app-placeholder): popup/overlay に DEFAULT_URL を
//     直書きすると、定数変更時に UI がドリフトする。契約値の直書きをソースで禁止する。
//   - dry-violation (ARCH-NEW-sleep-dup): content script が shared/dom の timing util を
//     再定義すると DRY 違反になる。一元化（shared/dom export）を機械担保する。
//     #847 で content.ts は固定 sleep を中断可能な abortableSleep へ置換し、sleep import を
//     除去する（noUnusedLocals）。ガードの intent（content は timing util を自前定義せず
//     shared/dom から import する）を新 API へ追従させる。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { DEFAULT_URL } from "../../shared/constants";
import { sleep } from "../../shared/dom";

const read = (rel: string): string =>
  readFileSync(fileURLToPath(new URL(rel, import.meta.url)), "utf8");

describe("ssot-drift: ローカル配信元 selector は候補 state を参照する", () => {
  const appSource = read("../components/App.tsx");

  it("Given App.tsx When 文字列を探す Then DEFAULT_URL の値を直書きしていない", () => {
    expect(appSource).not.toContain(DEFAULT_URL);
  });

  it("Given App.tsx When selector を読む Then serverSources を options として表示する", () => {
    expect(appSource).toMatch(/serverSources\.map/);
    expect(appSource).toMatch(/<select\s+value=\{url\}/);
  });
});

describe("dry-violation: timing util は shared/dom に一元化する", () => {
  const contentSource = read("../entrypoints/content.ts");

  it("Given shared/dom の sleep When 呼び出す Then 指定 ms 後に resolve する", async () => {
    await expect(sleep(0)).resolves.toBeUndefined();
  });

  it("Given content.ts When timing util の定義を探す Then 自前定義せず shared/dom から import する", () => {
    // content.ts は #847 で固定 sleep を捨て abortableSleep に統一する。timing util の
    // 自前定義を禁じ、shared/dom からの import を機械担保する。
    expect(contentSource).not.toMatch(/function sleep\b/);
    expect(contentSource).not.toMatch(/function abortableSleep\b/);
    expect(contentSource).toMatch(/^\s*abortableSleep,$/m);
  });
});
