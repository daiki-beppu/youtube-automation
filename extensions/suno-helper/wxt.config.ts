import { defineConfig } from "wxt";

import { SERVER_HOST_PERMISSIONS, SUNO_MATCHES } from "../shared/constants";
import { MANIFEST_PERMISSIONS } from "./lib/manifest";

// See https://wxt.dev/api/config.html
export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  manifest: {
    name: "Suno Helper (youtube-channels-automation)",
    description: "/suno が生成した Style/Lyrics を Suno Custom Mode に順次注入し Generate を連続実行する補助拡張。",
    // 最小権限。SSOT は lib/manifest.ts (tests/manifest.test.ts で機械担保)。
    permissions: [...MANIFEST_PERMISSIONS],
    host_permissions: [...SERVER_HOST_PERMISSIONS, ...SUNO_MATCHES],
    action: {
      default_title: "Suno Helper",
    },
  },
});
