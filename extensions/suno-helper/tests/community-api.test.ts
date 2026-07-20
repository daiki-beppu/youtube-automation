import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type CommunityPost,
  fetchCommunityImage,
  fetchCommunityPosts,
} from "../../shared/api";
import { COMMUNITY_PHASE, type CommunityPhase } from "../../shared/constants";

const BASE_URL = "http://localhost:7873";

function mockFetch(impl: () => Partial<Response>) {
  const fn = vi.fn(async () => impl() as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("shared community API", () => {
  it("投稿配列をルート定数の URL から取得する", async () => {
    const posts: CommunityPost[] = [
      {
        text: "公開のお知らせ",
        scheduled_at: "2026-07-19T18:00:00+09:00",
        image_path: "collections/planning/demo-collection/main.png",
        visibility: "public",
      },
    ];
    const fetchFn = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => posts,
    }));

    await expect(fetchCommunityPosts(`${BASE_URL}/`)).resolves.toEqual(posts);
    expect(fetchFn).toHaveBeenCalledWith(`${BASE_URL}/community/posts.json`);
  });

  it.each([
    ["404", { ok: false, status: 404, json: async () => [] }],
    ["空配列", { ok: true, status: 200, json: async () => [] }],
    ["非配列", { ok: true, status: 200, json: async () => ({ posts: [] }) }],
  ])("%s response は fail-loud で reject する", async (_label, response) => {
    mockFetch(() => response);

    await expect(fetchCommunityPosts(BASE_URL)).rejects.toThrow();
  });

  it("投稿 index の画像を Blob で返す", async () => {
    const image = new Blob(["image"], { type: "image/png" });
    const fetchFn = mockFetch(() => ({
      ok: true,
      status: 200,
      blob: async () => image,
    }));

    await expect(fetchCommunityImage(`${BASE_URL}/`, 2)).resolves.toBe(image);
    expect(fetchFn).toHaveBeenCalledWith(`${BASE_URL}/community/posts/2/image`);
  });

  it("画像 endpoint の非 2xx を fail-loud で reject する", async () => {
    mockFetch(() => ({ ok: false, status: 404 }));

    await expect(fetchCommunityImage(BASE_URL, 0)).rejects.toThrow("HTTP 404");
  });

  it("200 でも非画像 Content-Type の Blob は reject する", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      blob: async () => new Blob(["{}"], { type: "application/json" }),
    }));

    await expect(fetchCommunityImage(BASE_URL, 0)).rejects.toThrow(
      "image Content-Type"
    );
  });

  it.each([-1, 0.5, Number.NaN, Number.MAX_SAFE_INTEGER + 1, 1e21])(
    "不正 index %s は fetch 前に reject する",
    async (index) => {
      const fetchFn = mockFetch(() => ({ ok: true, status: 200 }));

      await expect(fetchCommunityImage(BASE_URL, index)).rejects.toThrow(
        "safe integer"
      );
      expect(fetchFn).not.toHaveBeenCalled();
    }
  );

  it.each([
    "2026-02-30T00:00:00+09:00",
    "2025-02-29T00:00:00+09:00",
    "2026-13-01T00:00:00+09:00",
    "2026-01-01T24:00:00+09:00",
  ])("不正な予約日時 %s は reject する", async (scheduledAt) => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => [{ text: "post", scheduled_at: scheduledAt }],
    }));

    await expect(fetchCommunityPosts(BASE_URL)).rejects.toThrow("ISO 8601");
  });
});

describe("COMMUNITY_PHASE", () => {
  it("community runner の全フェーズを import 可能な定数として公開する", () => {
    expect(COMMUNITY_PHASE).toEqual({
      INJECTING: "injecting",
      POSTING: "posting",
      SCHEDULING: "scheduling",
      UPLOADING_IMAGE: "uploading-image",
      DONE: "done",
      ERROR: "error",
    });
    const phases: CommunityPhase[] = Object.values(COMMUNITY_PHASE);
    expect(phases).toHaveLength(6);
  });
});
