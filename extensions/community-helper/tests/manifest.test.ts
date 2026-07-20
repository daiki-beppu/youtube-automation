import { describe, expect, it } from "vitest";

import {
  MANIFEST_CONTENT_SCRIPT_MATCHES,
  MANIFEST_HOST_PERMISSIONS,
  MANIFEST_PERMISSIONS,
} from "../lib/manifest";
import wxtConfig from "../wxt.config";

const POSTS_MATCH = "https://www.youtube.com/channel/*/posts*";

describe("community-helper manifest minimum permissions", () => {
  it("keeps runtime permissions limited to overlay storage and activeTab", () => {
    expect([...MANIFEST_PERMISSIONS]).toEqual(["storage", "activeTab"]);
  });

  it("limits content injection to channel posts and host access to loopback servers", () => {
    expect([...MANIFEST_CONTENT_SCRIPT_MATCHES]).toEqual([POSTS_MATCH]);
    expect([...MANIFEST_HOST_PERMISSIONS]).toEqual([
      "http://*.localhost/*",
      "http://localhost/*",
      "http://127.0.0.1/*",
    ]);
  });

  it("uses the manifest constants as the WXT single source of truth", () => {
    const manifest = wxtConfig.manifest as {
      permissions?: string[];
      host_permissions?: string[];
    };
    expect(manifest.permissions).toEqual([...MANIFEST_PERMISSIONS]);
    expect(manifest.host_permissions).toEqual([...MANIFEST_HOST_PERMISSIONS]);
  });

  it("has no native popup so action click can toggle the overlay", () => {
    const action = (
      wxtConfig.manifest as { action?: { default_popup?: string } }
    ).action;
    expect(action?.default_popup).toBeUndefined();
  });
});
