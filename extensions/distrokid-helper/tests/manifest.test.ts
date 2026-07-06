import { describe, expect, it } from "vitest";

import { MANIFEST_CONTENT_SCRIPT_MATCHES, MANIFEST_HOST_PERMISSIONS, MANIFEST_PERMISSIONS } from "../lib/manifest";
import wxtConfig from "../wxt.config";

const EXPECTED_PERMISSIONS = ["storage", "activeTab"];
const EXPECTED_HOST_PERMISSIONS = ["*://*.distrokid.com/*"];
const EXPECTED_CONTENT_SCRIPT_MATCHES = ["*://*.distrokid.com/new*"];
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

  it("Given MANIFEST_CONTENT_SCRIPT_MATCHES When 中身を読む Then /new 限定である", () => {
    expect([...MANIFEST_CONTENT_SCRIPT_MATCHES]).toEqual(EXPECTED_CONTENT_SCRIPT_MATCHES);
  });
});

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
