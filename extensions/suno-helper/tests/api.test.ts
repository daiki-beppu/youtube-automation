// yt-collection-serve の `/suno/prompts.json` クライアントの契約テスト。
// 旧 `popup.js:54-60` の fetch ロジックを保持する:
//   - fetch 先は `${baseUrl}${PROMPTS_ROUTE}` (= `${baseUrl}/suno/prompts.json`)
//   - HTTP 非 2xx で throw
//   - 配列でない / 空配列の JSON で throw (fail-loud、silent 続行しない)
//   - 成功時は PromptEntry[] を返す
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchPrompts } from "../../shared/api";

const BASE_URL = "http://localhost:7873";
const PROMPTS_URL = `${BASE_URL}/suno/prompts.json`;

function mockFetch(impl: () => Partial<Response>) {
  const fn = vi.fn(async () => impl() as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("shared/api fetchPrompts: 配信元 URL の組み立て", () => {
  it("Given baseUrl When fetch する Then `/suno/prompts.json` サブパスへ要求する", async () => {
    const fetchFn = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => [{ name: "p1", style: "lofi", lyrics: "" }],
    }));

    await fetchPrompts(BASE_URL);

    expect(fetchFn).toHaveBeenCalledWith(PROMPTS_URL);
  });
});

describe("shared/api fetchPrompts: 正常系", () => {
  it("Given 配列 JSON When fetch する Then PromptEntry[] を返す", async () => {
    const entries = [
      { name: "夜更けのカフェ", style: "lofi, jazzy", lyrics: "la la la" },
      { name: "instrumental", style: "ambient", lyrics: "" },
    ];
    mockFetch(() => ({ ok: true, status: 200, json: async () => entries }));

    const result = await fetchPrompts(BASE_URL);

    expect(result).toEqual(entries);
    expect(result[0]).toMatchObject({
      name: expect.any(String),
      style: expect.any(String),
      lyrics: expect.any(String),
    });
  });
});

describe("shared/api fetchPrompts: 異常系 (fail-loud)", () => {
  it("Given HTTP 500 When fetch する Then ステータスを含めて throw する", async () => {
    mockFetch(() => ({ ok: false, status: 500, json: async () => ({}) }));

    await expect(fetchPrompts(BASE_URL)).rejects.toThrow(/500/);
  });

  it("Given 配列でない JSON (オブジェクト) When fetch する Then throw する", async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => ({ name: "x" }) }));

    await expect(fetchPrompts(BASE_URL)).rejects.toThrow();
  });

  it("Given 空配列 When fetch する Then throw する", async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => [] }));

    await expect(fetchPrompts(BASE_URL)).rejects.toThrow();
  });
});
