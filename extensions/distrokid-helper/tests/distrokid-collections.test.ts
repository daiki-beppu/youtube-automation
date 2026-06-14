// shared/api の DistroKid collection 選択機能の契約テスト (#934)。
//
// サーバー契約（issue #934）:
//   - GET /distrokid/collections -> DistrokidCollectionSummary[] (dir mode のみ。単一 mode は 404)
//   - POST /distrokid/releases   -> 配信済み記録（body: { collection_id, disc, album_title }）
//
// テスト対象: fetchDistrokidCollections / excludeReleasedDiscs / recordDistrokidRelease
// および shared/constants の distrokidReleaseRoute（契約文字列の固定テスト）。

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  fetchDistrokidCollections,
  excludeReleasedDiscs,
  recordDistrokidRelease,
  type DistrokidCollectionSummary,
} from "../../shared/api";
import { distrokidReleaseRoute } from "../../shared/constants";

const BASE_URL = "http://localhost:7873";

// DistrokidCollectionSummary のサンプル fixtures。
const DISC_UNRELEASED: DistrokidCollectionSummary = {
  collection_id: "20260526-soulful-grooves-coding-focus-collection",
  name: "coding focus",
  disc: "disc1-coding-focus-vol1",
  album_title: "Coding Focus Vol.1",
  track_count: 10,
  released: false,
};

const DISC_RELEASED: DistrokidCollectionSummary = {
  collection_id: "20260526-soulful-grooves-coding-focus-collection",
  name: "coding focus",
  disc: "disc2-coding-focus-vol2",
  album_title: "Coding Focus Vol.2",
  track_count: 8,
  released: true,
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// --- distrokidReleaseRoute: 契約文字列の固定テスト ---

describe("distrokidReleaseRoute", () => {
  it("Given collection_id と disc When 組み立てる Then 正しいパスを返す", () => {
    // ルートの形式は `/collections/<id>/distrokid/<disc>/release.json` (#934 契約)。
    expect(
      distrokidReleaseRoute(
        "20260526-soulful-grooves-coding-focus-collection",
        "disc1-coding-focus-vol1",
      ),
    ).toBe(
      "/collections/20260526-soulful-grooves-coding-focus-collection/distrokid/disc1-coding-focus-vol1/release.json",
    );
  });

  it("別の collection_id / disc でも同じパターンを返す", () => {
    expect(distrokidReleaseRoute("20261001-rjn-dawn-collection", "disc1")).toBe(
      "/collections/20261001-rjn-dawn-collection/distrokid/disc1/release.json",
    );
  });
});

// --- fetchDistrokidCollections ---

describe("fetchDistrokidCollections", () => {
  it("200 のとき DistrokidCollectionSummary[] を返す", async () => {
    // Given
    fetchMock.mockResolvedValue(
      jsonResponse(200, [DISC_UNRELEASED, DISC_RELEASED]),
    );

    // When
    const result = await fetchDistrokidCollections(BASE_URL);

    // Then
    expect(result).toHaveLength(2);
    expect(result[0]).toEqual(DISC_UNRELEASED);
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/distrokid/collections`,
    );
  });

  it("空配列 JSON のとき 0 件の配列を返す（0 件 = 未配信 disc なしの正常ケース）", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(200, []));

    // When
    const result = await fetchDistrokidCollections(BASE_URL);

    // Then: 空配列は throw せず返す（全件配信済みの正常ケースに使う）。
    expect(result).toHaveLength(0);
  });

  it("404 のとき throw する（単一 mode サーバーの fallback トリガー）", async () => {
    // Given: 単一 mode サーバーは /distrokid/collections が 404 を返す。
    fetchMock.mockResolvedValue(jsonResponse(404, {}));

    // When / Then
    await expect(fetchDistrokidCollections(BASE_URL)).rejects.toThrow();
  });

  it("500 のとき汎用 Error を throw する", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(500, {}));

    // When / Then
    await expect(fetchDistrokidCollections(BASE_URL)).rejects.toThrow(
      "HTTP 500",
    );
  });

  it("配列でない JSON のとき throw する", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(200, { error: "not an array" }));

    // When / Then
    await expect(fetchDistrokidCollections(BASE_URL)).rejects.toThrow(
      "配列ではない JSON が返りました。",
    );
  });
});

// --- excludeReleasedDiscs ---

describe("excludeReleasedDiscs", () => {
  it("released===true の disc を除外し released===false を残す", () => {
    // Given
    const input = [DISC_UNRELEASED, DISC_RELEASED];

    // When
    const result = excludeReleasedDiscs(input);

    // Then
    expect(result).toHaveLength(1);
    expect(result[0].disc).toBe("disc1-coding-focus-vol1");
  });

  it("全件 released===false のとき全件を返す", () => {
    // Given: 未配信 2 件。
    const input: DistrokidCollectionSummary[] = [
      { ...DISC_UNRELEASED },
      { ...DISC_UNRELEASED, disc: "disc2", album_title: "Vol.2" },
    ];

    // When
    const result = excludeReleasedDiscs(input);

    // Then
    expect(result).toHaveLength(2);
  });

  it("全件 released===true のとき空配列を返す", () => {
    // Given: 全件配信済み。
    const input: DistrokidCollectionSummary[] = [
      { ...DISC_RELEASED },
      { ...DISC_RELEASED, disc: "disc3", album_title: "Vol.3" },
    ];

    // When
    const result = excludeReleasedDiscs(input);

    // Then
    expect(result).toHaveLength(0);
  });

  it("空配列のとき空配列を返す", () => {
    expect(excludeReleasedDiscs([])).toHaveLength(0);
  });
});

// --- recordDistrokidRelease ---

describe("recordDistrokidRelease", () => {
  it("200 のとき void を返す（POST body と URL の確認）", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(200, {}));

    // When
    await recordDistrokidRelease(BASE_URL, {
      collection_id: DISC_UNRELEASED.collection_id,
      disc: DISC_UNRELEASED.disc,
      album_title: DISC_UNRELEASED.album_title,
    });

    // Then: 正しい URL と body で POST する。
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/distrokid/releases`,
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          collection_id: DISC_UNRELEASED.collection_id,
          disc: DISC_UNRELEASED.disc,
          album_title: DISC_UNRELEASED.album_title,
        }),
      }),
    );
  });

  it("非 OK のとき throw する（caller が warn 処理する）", async () => {
    // Given: サーバーエラー（500 等）のとき throw して caller に伝える。
    fetchMock.mockResolvedValue(jsonResponse(500, {}));

    // When / Then
    await expect(
      recordDistrokidRelease(BASE_URL, {
        collection_id: "col-id",
        disc: "disc1",
        album_title: "Album",
      }),
    ).rejects.toThrow("HTTP 500");
  });

  it("204 でも成功とみなす（No Content レスポンス対応）", async () => {
    // Given: 一部サーバーは 204 No Content で応答する。
    fetchMock.mockResolvedValue(jsonResponse(204, null));

    // When / Then: throw しない。
    await expect(
      recordDistrokidRelease(BASE_URL, {
        collection_id: "col-id",
        disc: "disc1",
        album_title: "Album",
      }),
    ).resolves.toBeUndefined();
  });
});
