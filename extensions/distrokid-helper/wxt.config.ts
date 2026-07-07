import { defineConfig } from "wxt";

import { SERVER_HOST_PERMISSIONS } from "../shared/constants";
import { MANIFEST_HOST_PERMISSIONS, MANIFEST_PERMISSIONS } from "./lib/manifest";

// WXT 設定。最小権限で Manifest V3 を生成する（要件 #2）。
export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  manifest: {
    name: "DistroKid Helper (TEST)",
    description: "DistroKid 登録フォームに静的プロファイル + 動的データを自動入力する",
    action: {
      default_title: "DistroKid Helper (TEST)",
    },
    // 最小権限。SSOT は lib/manifest.ts (tests/manifest.test.ts で機械担保)。
    permissions: [...MANIFEST_PERMISSIONS],
    host_permissions: [...MANIFEST_HOST_PERMISSIONS, ...SERVER_HOST_PERMISSIONS],
  },
});
