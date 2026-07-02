// suno-helper の tests/manifest.test.ts と同型の最小権限契約（ADR-0016 の shell parity）。
// manifest は `wxt.config.ts` から自動生成されるため、権限宣言を import 可能な
// 単一定数 `MANIFEST_PERMISSIONS` / `MANIFEST_HOST_PERMISSIONS` (lib/manifest.ts) に
// 切り出し、wxt.config.ts はその定数を参照する。これにより未使用権限の混入を機械的に防ぐ。
//
// 契約: storage / activeTab のみ。suno-helper が持つ tabs / downloads / debugger も
// distrokid-helper では不要（bg tab 操作・DL 監視・trusted dispatch を行わない）ため
// 禁止権限として回帰検知する。host permissions は distrokid.com 限定
// （release.json / asset の fetch は popup origin で行うためサーバー向け許可は不要）。
import { describe, expect, it } from "vitest";

import { MANIFEST_HOST_PERMISSIONS, MANIFEST_PERMISSIONS } from "../lib/manifest";
import wxtConfig from "../wxt.config";

const EXPECTED_PERMISSIONS = ["storage", "activeTab"];
const EXPECTED_HOST_PERMISSIONS = ["*://*.distrokid.com/*"];
// 広域権限に加え、suno-helper 専用権限の混入（shell コピー時の permission creep）も検知する。
const FORBIDDEN_PERMISSIONS = ["history", "bookmarks", "cookies", "webNavigation", "tabs", "downloads", "debugger"];

describe("lib/manifest: 最小権限契約", () => {
  it("Given MANIFEST_PERMISSIONS When 中身を読む Then storage / activeTab である", () => {
    expect(new Set(MANIFEST_PERMISSIONS)).toEqual(new Set(EXPECTED_PERMISSIONS));
  });

  it("Given MANIFEST_PERMISSIONS When 重複の有無を見る Then 2 件ちょうどである", () => {
    expect(MANIFEST_PERMISSIONS).toHaveLength(EXPECTED_PERMISSIONS.length);
  });

  it("Given MANIFEST_PERMISSIONS When 過剰権限を探す Then 広域権限と suno-helper 専用権限を含まない", () => {
    for (const forbidden of FORBIDDEN_PERMISSIONS) {
      expect(MANIFEST_PERMISSIONS).not.toContain(forbidden);
    }
  });

  it("Given MANIFEST_HOST_PERMISSIONS When 中身を読む Then distrokid.com 限定である", () => {
    expect([...MANIFEST_HOST_PERMISSIONS]).toEqual(EXPECTED_HOST_PERMISSIONS);
  });
});

// 定数だけを検証すると wxt.config.ts:permissions に定数を介さず直接権限を
// 追記された場合を検知できない。生成 manifest の入力源である wxt.config の
// manifest.permissions / host_permissions が定数と一致することを表明し、
// SSOT 迂回を機械的に塞ぐ。
// (生成成果物 `.output/chrome-mv3/manifest.json` 自体の検証は CI の build 後ステップが担う)
describe("wxt.config: manifest 権限の SSOT 一致", () => {
  it("Given wxt.config の manifest When permissions を読む Then MANIFEST_PERMISSIONS と一致する", () => {
    const manifest = wxtConfig.manifest;
    expect(typeof manifest).toBe("object");
    expect((manifest as { permissions?: string[] }).permissions).toEqual([...MANIFEST_PERMISSIONS]);
  });

  it("Given wxt.config の manifest When host_permissions を読む Then MANIFEST_HOST_PERMISSIONS と一致する", () => {
    const manifest = wxtConfig.manifest as { host_permissions?: string[] };
    expect(manifest.host_permissions).toEqual([...MANIFEST_HOST_PERMISSIONS]);
  });

  it("Given wxt.config の manifest When 過剰権限を探す Then 広域権限と suno-helper 専用権限を含まない", () => {
    const manifest = wxtConfig.manifest as { permissions?: string[] };
    for (const forbidden of FORBIDDEN_PERMISSIONS) {
      expect(manifest.permissions).not.toContain(forbidden);
    }
  });
});
