// `/distrokid/release.json` / `/distrokid/assets/<path>` を fetch する API client。
//
// サーバー契約（src/youtube_automation/scripts/distrokid_release.py）:
//   - GET <baseUrl>/distrokid/release.json -> { profile, release } envelope  （単一 mode）
//   - GET <baseUrl>/collections/<id>/distrokid/<disc>/release.json -> 同形 （dir mode、#934）
//   - GET <baseUrl><asset_path>            -> binary（asset_path は接頭辞込み）
//   - distrokid.enabled=false / 未配置のチャンネルは /distrokid/* が 404（要件 #16）

import { distrokidReleaseRoute } from "../../shared/constants";
import { encodeAsset, type SerializedAsset } from "./asset-transfer";
import type { ReleasePayload } from "./types";

// release.json のサブパス（サーバー側 DISTROKID_RELEASE_ROUTE と対称の契約文字列）。
const RELEASE_ROUTE = "/distrokid/release.json";

// release.json が 404 を返したことを表す専用エラー。
// 無効チャンネル（distrokid.enabled=false / 未配置）を popup がガイダンス表示で扱うために
// 汎用エラーと区別する（要件 #16）。
export class ReleaseUnavailableError extends Error {
  constructor(message = "distrokid release is unavailable (404)") {
    super(message);
    this.name = "ReleaseUnavailableError";
  }
}

// baseUrl 末尾スラッシュを除去し、サブパス連結時の二重スラッシュを防ぐ。
function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

// release.json を取得する。404 は ReleaseUnavailableError、その他の非 OK は汎用 Error。
export async function fetchRelease(baseUrl: string): Promise<ReleasePayload> {
  const url = `${normalizeBaseUrl(baseUrl)}${RELEASE_ROUTE}`;
  const response = await fetch(url, { method: "GET" });

  if (response.status === 404) {
    throw new ReleaseUnavailableError();
  }
  if (!response.ok) {
    throw new Error(`release.json fetch failed: HTTP ${response.status}`);
  }

  return (await response.json()) as ReleasePayload;
}

// dir mode の collection-scoped release.json を取得する (#934)。
// ルートは shared/constants の distrokidReleaseRoute で組み立て、文字列ハードコーディングを避ける。
// 404 は ReleaseUnavailableError、その他の非 OK は汎用 Error。
export async function fetchCollectionRelease(
  baseUrl: string,
  collectionId: string,
  disc: string,
): Promise<ReleasePayload> {
  const route = distrokidReleaseRoute(collectionId, disc);
  const url = `${normalizeBaseUrl(baseUrl)}${route}`;
  const response = await fetch(url, { method: "GET" });

  if (response.status === 404) {
    throw new ReleaseUnavailableError();
  }
  if (!response.ok) {
    throw new Error(`release.json fetch failed: HTTP ${response.status}`);
  }

  return (await response.json()) as ReleasePayload;
}

// asset（曲 / ジャケット）を取得し、content へ転送するため直列化して返す。
// fetch は popup（chrome-extension:// origin）で行う必要がある（asset-transfer.ts 参照）。
// assetPath は接頭辞 "/distrokid/assets/" または "/collections/<id>/distrokid/assets/" 込みのため
// baseUrl と連結するだけでよい（dir mode の collection-scoped asset_path も同形式）。
export async function fetchAsset(
  baseUrl: string,
  assetPath: string,
  filename: string,
): Promise<SerializedAsset> {
  const url = `${normalizeBaseUrl(baseUrl)}${assetPath}`;
  const response = await fetch(url, { method: "GET" });

  if (!response.ok) {
    throw new Error(`asset fetch failed (${assetPath}): HTTP ${response.status}`);
  }

  return encodeAsset(filename, await response.blob());
}
