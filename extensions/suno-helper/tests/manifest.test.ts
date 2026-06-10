// 旧 `tests/test_suno_extension_manifest.py` の最小権限契約 (#692 least-privilege) を
// WXT 構成へ移管したもの。manifest は `wxt.config.ts` から自動生成されるため、
// 権限宣言を import 可能な単一定数 `MANIFEST_PERMISSIONS` (lib/manifest.ts) に切り出し、
// wxt.config.ts はその定数を参照する。これにより未使用権限の混入を機械的に防ぐ。
//
// 契約 (#893 で `tabs` を追加): chrome.storage.local + activeTab + tabs。
// `tabs` は自動 POST trigger（background が `https://suno.com/me` を bg tab で開閉し
// playlist を scrape → POST する、追加要件 A）で `browser.tabs.create / remove` を呼ぶために必要。
// それ以外の広域権限（history / bookmarks / cookies 等）は引き続き混入させない。
import { describe, expect, it } from "vitest";

import { MANIFEST_PERMISSIONS } from "../lib/manifest";
import wxtConfig from "../wxt.config";

const EXPECTED_PERMISSIONS = ["storage", "activeTab", "tabs"];
// `tabs` 追加後も混入させたくない広域権限（過剰権限 creep の回帰検知）。
const FORBIDDEN_PERMISSIONS = ["history", "bookmarks", "cookies", "webNavigation"];

describe("lib/manifest: 最小権限契約", () => {
  it("Given MANIFEST_PERMISSIONS When 中身を読む Then storage / activeTab / tabs である", () => {
    expect(new Set(MANIFEST_PERMISSIONS)).toEqual(new Set(EXPECTED_PERMISSIONS));
  });

  it("Given MANIFEST_PERMISSIONS When 重複の有無を見る Then 3 件ちょうどである", () => {
    expect(MANIFEST_PERMISSIONS).toHaveLength(EXPECTED_PERMISSIONS.length);
  });

  it("Given MANIFEST_PERMISSIONS When 自動 POST trigger 用権限を確認する Then `tabs` を含む", () => {
    expect(MANIFEST_PERMISSIONS).toContain("tabs");
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
    expect((manifest as { permissions?: string[] }).permissions).toEqual([...MANIFEST_PERMISSIONS]);
  });

  it("Given wxt.config の manifest When 過剰権限を探す Then 広域権限を含まない", () => {
    const manifest = wxtConfig.manifest as { permissions?: string[] };
    for (const forbidden of FORBIDDEN_PERMISSIONS) {
      expect(manifest.permissions).not.toContain(forbidden);
    }
  });
});
