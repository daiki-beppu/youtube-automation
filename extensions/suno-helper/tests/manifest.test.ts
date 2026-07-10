// 旧 `tests/test_suno_extension_manifest.py` の最小権限契約 (#692 least-privilege) を
// WXT 構成へ移管したもの。manifest は `wxt.config.ts` から自動生成されるため、
// 権限宣言を import 可能な単一定数 `MANIFEST_PERMISSIONS` (lib/manifest.ts) に切り出し、
// wxt.config.ts はその定数を参照する。これにより未使用権限の混入を機械的に防ぐ。
//
// 契約 (#1146 で `downloads`、#1251 で `debugger` を追加):
//   storage / activeTab / downloads / debugger / scripting。
// `downloads` は Suno playlist の ZIP ダウンロード監視、`debugger` は trusted Cmd+P dispatch に必要。
// それ以外の広域権限（history / bookmarks / cookies 等）は引き続き混入させない。
import { describe, expect, it } from "vitest";

import { MANIFEST_PERMISSIONS } from "../lib/manifest";
import wxtConfig from "../wxt.config";

const EXPECTED_PERMISSIONS = ["storage", "activeTab", "downloads", "debugger", "scripting"];
// Download all / trusted Cmd+P 追加後も混入させたくない広域権限（過剰権限 creep の回帰検知）。
const FORBIDDEN_PERMISSIONS = ["history", "bookmarks", "cookies", "webNavigation"];

describe("lib/manifest: 最小権限契約", () => {
  it("Given MANIFEST_PERMISSIONS When 中身を読む Then自己復旧に必要な scripting を含む", () => {
    expect(new Set(MANIFEST_PERMISSIONS)).toEqual(new Set(EXPECTED_PERMISSIONS));
  });

  it("Given MANIFEST_PERMISSIONS When 重複の有無を見る Then EXPECTED_PERMISSIONS と同数である", () => {
    expect(MANIFEST_PERMISSIONS).toHaveLength(EXPECTED_PERMISSIONS.length);
  });

  it("Given MANIFEST_PERMISSIONS When ダウンロード監視用権限を確認する Then `downloads` を含む (#1146)", () => {
    expect(MANIFEST_PERMISSIONS).toContain("downloads");
  });

  it("Given MANIFEST_PERMISSIONS When trusted Cmd+P 用権限を確認する Then `debugger` を含む (#1251)", () => {
    expect(MANIFEST_PERMISSIONS).toContain("debugger");
  });

  it("Given MANIFEST_PERMISSIONS When content script 自己復旧用権限を確認する Then `scripting` を含む", () => {
    expect(MANIFEST_PERMISSIONS).toContain("scripting");
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

// MAIN world fetch bridge (#948) は filterEntrypoints に載らないと build から落ちて
// silent に DOM プロキシ縮退し続ける。entrypoint の登録漏れを機械的に塞ぐ。
// （bridge は権限を一切追加しない設計: 上の permissions 検証が据え置きであることと対）
describe("wxt.config: suno-bridge entrypoint の登録 (#948)", () => {
  it("Given filterEntrypoints When 読む Then suno-bridge を含む", () => {
    expect(wxtConfig.filterEntrypoints).toContain("suno-bridge");
  });
});
