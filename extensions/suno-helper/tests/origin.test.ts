// origin allowlist は yt-collection-serve の CORS 判定
// (`collection_serve.py::is_origin_allowed`) と対の契約。サーバー側 SSOT の
// 各分岐を拡張側でも同じ真偽値で再現することを保証する。
//   - allowOrigin=null  → `chrome-extension://` scheme のみ許可
//   - allowOrigin 指定時 → その値との完全一致のみ許可
//   - origin が空/欠落  → 常に false
import { describe, expect, it } from "vitest";

import { isOriginAllowed } from "../../shared/origin";

describe("shared/origin: allowOrigin 未指定 (chrome-extension:// scheme 許可)", () => {
  it("Given 拡張オリジン When 判定する Then 許可する", () => {
    expect(isOriginAllowed("chrome-extension://abcdefghijklmnop", null)).toBe(true);
  });

  it("Given 非拡張オリジン When 判定する Then 拒否する", () => {
    expect(isOriginAllowed("https://suno.com", null)).toBe(false);
  });

  it("Given scheme だけ似せた偽装オリジン When 判定する Then 拒否する", () => {
    expect(isOriginAllowed("https://chrome-extension.evil.com", null)).toBe(false);
  });
});

describe("shared/origin: allowOrigin 指定時 (完全一致のみ)", () => {
  it("Given allowOrigin と完全一致 When 判定する Then 許可する", () => {
    const allow = "chrome-extension://abcdefghijklmnop";
    expect(isOriginAllowed(allow, allow)).toBe(true);
  });

  it("Given allowOrigin と不一致の拡張オリジン When 判定する Then 拒否する", () => {
    expect(isOriginAllowed("chrome-extension://zzzzzzzzzzzzzzzz", "chrome-extension://abcdefghijklmnop")).toBe(false);
  });

  it("Given allowOrigin が非拡張 URL で完全一致 When 判定する Then 許可する (scheme 不問)", () => {
    expect(isOriginAllowed("https://example.com", "https://example.com")).toBe(true);
  });
});

describe("shared/origin: 空 / 欠落 origin", () => {
  it("Given null origin When 判定する Then 拒否する", () => {
    expect(isOriginAllowed(null, null)).toBe(false);
  });

  it("Given 空文字 origin When 判定する Then 拒否する", () => {
    expect(isOriginAllowed("", null)).toBe(false);
  });

  it("Given undefined origin When 判定する Then 拒否する", () => {
    expect(isOriginAllowed(undefined, null)).toBe(false);
  });
});
