// manifest 権限の最小権限契約 (#1036)。suno-helper の同等テストに倣い、
// MANIFEST_PERMISSIONS の中身検証 + wxt.config の SSOT 一致検証 + 禁止権限の不在検証を行う。
// distrokid-helper は tabs 不要（bg tab 操作を行わない）ため、suno-helper とは権限セットが異なる。
import { describe, expect, it } from "vitest";

import { MANIFEST_PERMISSIONS } from "../lib/manifest";
import wxtConfig from "../wxt.config";

const EXPECTED_PERMISSIONS = ["storage", "activeTab"];
// 混入させたくない広域権限（過剰権限 creep の回帰検知）。
const FORBIDDEN_PERMISSIONS = [
  "tabs",
  "history",
  "bookmarks",
  "cookies",
  "webNavigation",
];

describe("lib/manifest: 最小権限契約", () => {
  it("Given MANIFEST_PERMISSIONS When 中身を読む Then storage / activeTab である", () => {
    expect(new Set(MANIFEST_PERMISSIONS)).toEqual(new Set(EXPECTED_PERMISSIONS));
  });

  it("Given MANIFEST_PERMISSIONS When 重複の有無を見る Then 2 件ちょうどである", () => {
    expect(MANIFEST_PERMISSIONS).toHaveLength(EXPECTED_PERMISSIONS.length);
  });

  it("Given MANIFEST_PERMISSIONS When 過剰権限を探す Then 広域権限を含まない", () => {
    for (const forbidden of FORBIDDEN_PERMISSIONS) {
      expect(MANIFEST_PERMISSIONS).not.toContain(forbidden);
    }
  });
});

// 定数だけを検証すると wxt.config.ts:permissions に定数を介さず直接権限を
// 追記された場合を検知できない。生成 manifest の入力源である wxt.config の
// manifest.permissions が定数と一致することを表明し、SSOT 迂回を機械的に塞ぐ。
// (生成成果物 `.output/chrome-mv3/manifest.json` 自体の検証は CI の build 後ステップが担う)
describe("wxt.config: manifest 権限の SSOT 一致", () => {
  it("Given wxt.config の manifest When permissions を読む Then MANIFEST_PERMISSIONS と一致する", () => {
    const manifest = wxtConfig.manifest;
    expect(typeof manifest).toBe("object");
    expect(
      (manifest as { permissions?: string[] }).permissions,
    ).toEqual([...MANIFEST_PERMISSIONS]);
  });

  it("Given wxt.config の manifest When 過剰権限を探す Then 広域権限を含まない", () => {
    const manifest = wxtConfig.manifest as { permissions?: string[] };
    for (const forbidden of FORBIDDEN_PERMISSIONS) {
      expect(manifest.permissions).not.toContain(forbidden);
    }
  });
});
