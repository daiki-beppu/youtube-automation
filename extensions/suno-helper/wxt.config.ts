import { defineConfig } from "wxt";

import { SERVER_HOST_PERMISSIONS, SUNO_MATCHES } from "../shared/constants";
import { MANIFEST_PERMISSIONS } from "./lib/manifest";

// See https://wxt.dev/api/config.html
export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  // popup 廃止 (#892 要件5): popup entrypoint を build 対象から外し manifest の default_popup を未指定化する。
  // これにより action クリックで chrome.action.onClicked が発火し overlay 表示を toggle できる。
  // popup のソース (entrypoints/popup/) はファイルとして残置し、物理削除は後続 PR に委ねる (order.md スコープ外)。
  // suno-bridge は MAIN world の fetch 観測 bridge (#948)。
  filterEntrypoints: ["background", "content", "overlay", "suno-bridge"],
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
