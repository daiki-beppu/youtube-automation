import { describe, expect, it } from "vitest";

import {
  MANIFEST_CONTENT_SCRIPT_MATCHES,
  MANIFEST_HOST_PERMISSIONS,
  MANIFEST_PERMISSIONS,
} from "../lib/manifest";
import wxtConfig from "../wxt.config";

const STUDIO_MATCH = "*://studio.youtube.com/*";

describe("community-helper manifest minimum permissions", () => {
  it("keeps runtime permissions limited to activeTab", () => {
    expect([...MANIFEST_PERMISSIONS]).toEqual(["activeTab"]);
  });

  it("keeps host permissions and content matches limited to YouTube Studio", () => {
    expect([...MANIFEST_HOST_PERMISSIONS]).toEqual([STUDIO_MATCH]);
    expect([...MANIFEST_CONTENT_SCRIPT_MATCHES]).toEqual([STUDIO_MATCH]);
  });

  it("uses the manifest constants as the WXT single source of truth", () => {
    const manifest = wxtConfig.manifest as {
      permissions?: string[];
      host_permissions?: string[];
    };
    expect(manifest.permissions).toEqual([...MANIFEST_PERMISSIONS]);
    expect(manifest.host_permissions).toEqual([...MANIFEST_HOST_PERMISSIONS]);
  });
});
