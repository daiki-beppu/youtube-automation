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
        "disc1-coding-focus-vol1"
      )
    ).toBe(
      "/collections/20260526-soulful-grooves-coding-focus-collection/distrokid/disc1-coding-focus-vol1/release.json"
    );
  });

  it("別の collection_id / disc でも同じパターンを返す", () => {
    expect(distrokidReleaseRoute("20261001-rjn-dawn-collection", "disc1")).toBe(
      "/collections/20261001-rjn-dawn-collection/distrokid/disc1/release.json"
    );
  });

  it("スペース入り collection_id は path segment encode する", () => {
    expect(
      distrokidReleaseRoute("20260526-rainy jazz-collection", "disc1")
    ).toBe(
      "/collections/20260526-rainy%20jazz-collection/distrokid/disc1/release.json"
    );
  });
});

// --- fetchDistrokidCollections ---

describe("fetchDistrokidCollections", () => {
  it("200 のとき DistrokidCollectionSummary[] を返す", async () => {
    // Given
    fetchMock.mockResolvedValue(
      jsonResponse(200, [DISC_UNRELEASED, DISC_RELEASED])
    );

    // When
    const result = await fetchDistrokidCollections(BASE_URL);

    // Then
    expect(result).toHaveLength(2);
    expect(result[0]).toEqual(DISC_UNRELEASED);
    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/distrokid/collections`);
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
      "HTTP 500"
    );
  });

  it("配列でない JSON のとき throw する", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(200, { error: "not an array" }));

    // When / Then
    await expect(fetchDistrokidCollections(BASE_URL)).rejects.toThrow(
      "配列ではない JSON が返りました。"
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
// #1360: serve token 必須の書き込み POST。GET /auth/token で token を取得してから
// X-Serve-Token 付きで POST し、403 は stale token とみなして 1 回だけ retry する
// （suno-helper の postDownloaded と同じ書き込み境界契約）。

const RELEASE_RECORD = {
  collection_id: DISC_UNRELEASED.collection_id,
  disc: DISC_UNRELEASED.disc,
  album_title: DISC_UNRELEASED.album_title,
};

/** /auth/token は 200 + token を返し、POST には指定応答を返す fetch mock。 */
function mockFetchWithToken(
  postResponse: () => Response,
  token = "test-token"
): void {
  fetchMock.mockImplementation(async (url: string) => {
    if (typeof url === "string" && url.includes("/auth/token")) {
      return jsonResponse(200, { token });
    }
    return postResponse();
  });
}

function postCalls(): Array<[string, RequestInit]> {
  return fetchMock.mock.calls.filter(
    (c) =>
      typeof c[0] === "string" &&
      (c[0] as string).includes("/distrokid/releases")
  ) as unknown as Array<[string, RequestInit]>;
}

describe("recordDistrokidRelease", () => {
  it("200 のとき void を返す（token 取得 → X-Serve-Token 付き POST の確認）", async () => {
    // Given
    mockFetchWithToken(() => jsonResponse(200, {}));

    // When
    await recordDistrokidRelease(BASE_URL, RELEASE_RECORD);

    // Then: token 取得 1 回 + POST 1 回。正しい URL / header / body で POST する。
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/auth/token`);
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/distrokid/releases`,
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Serve-Token": "test-token",
        },
        body: JSON.stringify(RELEASE_RECORD),
      })
    );
  });

  it("baseUrl 末尾 slash を正規化して token と POST の URL を組み立てる", async () => {
    // Given
    mockFetchWithToken(() => jsonResponse(200, {}));

    // When
    await recordDistrokidRelease(`${BASE_URL}/`, RELEASE_RECORD);

    // Then
    expect(fetchMock).toHaveBeenCalledWith(`${BASE_URL}/auth/token`);
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/distrokid/releases`,
      expect.anything()
    );
  });

  it("/auth/token が非 2xx のとき POST に進まず throw する", async () => {
    // Given: token 取得に失敗する（--allow-origin 未 lock のサーバー等）。
    fetchMock.mockResolvedValue(jsonResponse(403, {}));

    // When / Then
    await expect(
      recordDistrokidRelease(BASE_URL, RELEASE_RECORD)
    ).rejects.toThrow(/GET \/auth\/token failed: 403/);
    expect(postCalls()).toHaveLength(0);
  });

  it("POST が 403 のとき token を再取得して 1 回だけ retry し成功する（stale token）", async () => {
    // Given: 1 回目の POST は 403（サーバー再起動で token が stale）、2 回目は 200。
    let tokenCallCount = 0;
    let postCallCount = 0;
    fetchMock.mockImplementation(async (url: string) => {
      if (typeof url === "string" && url.includes("/auth/token")) {
        tokenCallCount += 1;
        return jsonResponse(200, {
          token: tokenCallCount === 1 ? "stale-token" : "fresh-token",
        });
      }
      postCallCount += 1;
      return postCallCount === 1
        ? jsonResponse(403, {})
        : jsonResponse(200, {});
    });

    // When / Then
    await expect(
      recordDistrokidRelease(BASE_URL, RELEASE_RECORD)
    ).resolves.toBeUndefined();

    // token 2 回 + POST 2 回 = 4 回。retry は再取得した fresh token を使う。
    expect(fetchMock).toHaveBeenCalledTimes(4);
    const posts = postCalls();
    expect(posts).toHaveLength(2);
    expect(
      (posts[1][1].headers as Record<string, string>)["X-Serve-Token"]
    ).toBe("fresh-token");
  });

  it("retry 後も 403 のとき throw する（無限 retry しない）", async () => {
    // Given: POST が常に 403。
    mockFetchWithToken(() => jsonResponse(403, {}));

    // When / Then: retry は 1 回まで（token 2 回 + POST 2 回）。
    await expect(
      recordDistrokidRelease(BASE_URL, RELEASE_RECORD)
    ).rejects.toThrow("HTTP 403");
    expect(postCalls()).toHaveLength(2);
  });

  it("非 OK（500 等）のとき throw する（caller が warn 処理する）", async () => {
    // Given: サーバーエラー（500 等）のとき throw して caller に伝える。
    mockFetchWithToken(() => jsonResponse(500, {}));

    // When / Then
    await expect(
      recordDistrokidRelease(BASE_URL, RELEASE_RECORD)
    ).rejects.toThrow("HTTP 500");
  });

  it("204 でも成功とみなす（No Content レスポンス対応）", async () => {
    // Given: 一部サーバーは 204 No Content で応答する。
    mockFetchWithToken(() => jsonResponse(204, null));

    // When / Then: throw しない。
    await expect(
      recordDistrokidRelease(BASE_URL, RELEASE_RECORD)
    ).resolves.toBeUndefined();
  });
});
