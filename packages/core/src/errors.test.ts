import { describe, expect, test } from "bun:test";
import { z } from "zod";
import {
  QuotaExhaustedError,
  ServiceError,
  YouTubeAPIError,
  toServiceError,
} from "./errors.ts";

// toServiceError は service 境界の唯一の例外 → ServiceError 変換口。
// ここで domain の精密判定が崩れると、CLI/MCP の retry semantic と
// JSON-RPC serialization 契約（ADR-0003 §2/§3）が静かに壊れるため、
// 既知の 7 入力パターンを domain 単位で固定する。
describe("toServiceError", () => {
  test("quota: QuotaExhaustedError を quota domain にマップする", () => {
    // Given: 429 固定 + retryAfterSeconds payload を持つ quota 例外
    const error = new QuotaExhaustedError("rate limited", { retryAfterSeconds: 30 });

    // When
    const result = toServiceError(error);

    // Then: api ではなく quota に落ちる（instanceof 判定順序の回帰ガード）
    expect(result.domain).toBe("quota");
    expect(result).toMatchObject({
      domain: "quota",
      httpStatus: 429,
      retryAfterSeconds: 30,
      message: "rate limited",
    });
    expect(() => ServiceError.parse(result)).not.toThrow();
  });

  test("api: YouTubeAPIError を api domain にマップし statusCode/reason を透過する", () => {
    // Given: statusCode + reason payload を持つ API 例外
    const error = new YouTubeAPIError("bad", { statusCode: 400, reason: "badRequest" });

    // When
    const result = toServiceError(error);

    // Then
    expect(result.domain).toBe("api");
    expect(result).toMatchObject({
      domain: "api",
      httpStatus: 400,
      reason: "badRequest",
      message: "bad",
    });
    expect(() => ServiceError.parse(result)).not.toThrow();
  });

  test("api: statusCode 未指定の YouTubeAPIError は httpStatus 500 にフォールバックする", () => {
    // Given: payload なしの API 例外（statusCode undefined）
    const error = new YouTubeAPIError("server exploded");

    // When
    const result = toServiceError(error);

    // Then: 500 default（`e.statusCode ?? 500` 契約）
    expect(result.domain).toBe("api");
    expect(result).toMatchObject({
      domain: "api",
      httpStatus: 500,
      message: "server exploded",
    });
    expect(() => ServiceError.parse(result)).not.toThrow();
  });

  test('auth: "auth:" prefix の plain Error を auth domain にマップする', () => {
    // Given: 名前タグ class を廃した prefix convention（auth:）
    const error = new Error("auth: token expired");

    // When
    const result = toServiceError(error);

    // Then: message を透過
    expect(result.domain).toBe("auth");
    expect(result).toMatchObject({ domain: "auth", message: "auth: token expired" });
    expect(() => ServiceError.parse(result)).not.toThrow();
  });

  test('config: "config:" prefix の plain Error を config domain にマップする', () => {
    // Given: prefix convention（config:）
    const error = new Error("config: missing key");

    // When
    const result = toServiceError(error);

    // Then
    expect(result.domain).toBe("config");
    expect(result).toMatchObject({ domain: "config", message: "config: missing key" });
    expect(() => ServiceError.parse(result)).not.toThrow();
  });

  test("validation: ZodError を validation domain にマップし field を path join する", () => {
    // Given: ネストした zod schema を不正値で parse して ZodError を得る
    let caught: unknown;
    try {
      z.object({ user: z.object({ name: z.string() }) }).parse({ user: { name: 1 } });
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(z.ZodError);

    // When
    const result = toServiceError(caught);

    // Then: issues[0].path（["user","name"]）を "." 結合した field
    expect(result.domain).toBe("validation");
    expect(result).toMatchObject({ domain: "validation", field: "user.name" });
    expect(() => ServiceError.parse(result)).not.toThrow();
  });

  test("validation: symbol を含む path の ZodError でも throw せず validation domain に落とす", () => {
    // Given: symbol key を持つ Map を parse 失敗させ、issues[0].path に symbol を含む ZodError を得る。
    // z.map は各 entry の path に実 key（ここでは symbol）を載せるため、path = [symbol, "value"] になる。
    let caught: unknown;
    try {
      z.map(z.symbol(), z.string()).parse(new Map([[Symbol("k"), 1]]));
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(z.ZodError);
    const hasSymbolPath = (caught as z.ZodError).issues.some((issue) =>
      issue.path.some((segment) => typeof segment === "symbol"),
    );
    expect(hasSymbolPath).toBe(true);

    // When / Then: 全域変換境界（ADR-0003 §3）は symbol path でも throw してはならない
    let result: ServiceError;
    expect(() => {
      result = toServiceError(caught);
    }).not.toThrow();
    expect(result!.domain).toBe("validation");
    expect(typeof (result! as { field?: string }).field).toBe("string");
    expect(() => ServiceError.parse(result!)).not.toThrow();
  });

  test("io: prefix なしの plain Error を io domain にマップする", () => {
    // Given: 既知 prefix を持たない Error
    const error = new Error("disk full");

    // When
    const result = toServiceError(error);

    // Then: message を透過
    expect(result.domain).toBe("io");
    expect(result).toMatchObject({ domain: "io", message: "disk full" });
    expect(() => ServiceError.parse(result)).not.toThrow();
  });

  test("unknown: 非 Error 値は String 化して io domain にマップする", () => {
    // Given: throw された非 Error 値（String(e) 経路）
    // When
    const result = toServiceError("boom");

    // Then
    expect(result.domain).toBe("io");
    expect(result).toMatchObject({ domain: "io", message: "boom" });
    expect(() => ServiceError.parse(result)).not.toThrow();
  });
});
