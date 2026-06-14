import { describe, expect, test } from "bun:test";
import { err, ok } from "./result.ts";

// Result は service 戻り値の唯一の成功/失敗表現（ADR-0003 §1）。
// ok/err helper が discriminator `ok` を正しく立てることを固定する。
describe("Result helpers", () => {
  test("ok: 成功値を { ok: true, value } に包む", () => {
    // Given/When
    const result = ok(42);

    // Then
    expect(result).toEqual({ ok: true, value: 42 });
  });

  test("err: エラー値を { ok: false, error } に包む", () => {
    // Given/When
    const result = err("boom");

    // Then
    expect(result).toEqual({ ok: false, error: "boom" });
  });

  test("ok/err: discriminator `ok` で成功と失敗を判別できる", () => {
    // Given/When/Then
    expect(ok(1).ok).toBe(true);
    expect(err(new Error("x")).ok).toBe(false);
  });
});
