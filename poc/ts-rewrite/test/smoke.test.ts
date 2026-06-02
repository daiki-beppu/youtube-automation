import { describe, expect, test } from "bun:test";
import { checkGoogleapis } from "../src/googleapis-check";
import { checkMcp } from "../src/mcp-check";
import { checkSharp } from "../src/sharp-check";

describe("ts-rewrite PoC smoke checks", () => {
  test("googleapis: 空 auth で認証拒否エラーになる", async () => {
    const result = await checkGoogleapis();
    expect(result.ok).toBe(true);
  });

  test("sharp: 生成 PNG を resize できる", async () => {
    const result = await checkSharp();
    expect(result.ok).toBe(true);
  });

  test("mcp-sdk: Server オブジェクトを生成できる", async () => {
    const result = await checkMcp();
    expect(result.ok).toBe(true);
  });

  // 撤退判定サマリ契約の回帰防止（family_tag: dead-branch）。
  // 各 check は失敗時も throw せず CheckResult を返す責務を持つ。
  // ここが崩れると run-smoke が verdict 出力前にクラッシュし go/no-go 判定が欠落する。
  test("撤退判定サマリ契約: 各 check は throw せず整形済み CheckResult を返す", async () => {
    for (const check of [checkGoogleapis, checkSharp, checkMcp]) {
      const result = await check();
      expect(typeof result.name).toBe("string");
      expect(result.name.length).toBeGreaterThan(0);
      expect(typeof result.ok).toBe("boolean");
      expect(typeof result.detail).toBe("string");
    }
  });
});
