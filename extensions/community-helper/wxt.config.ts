import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "wxt";

import {
  MANIFEST_HOST_PERMISSIONS,
  MANIFEST_PERMISSIONS,
} from "./lib/manifest";

export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  vite: () => ({ plugins: [tailwindcss()] }),
  manifest: {
    name: "Community Helper",
    description: "YouTube のコミュニティ投稿をスケジュールする",
    action: { default_title: "Community Helper" },
    permissions: [...MANIFEST_PERMISSIONS],
    host_permissions: [...MANIFEST_HOST_PERMISSIONS],
  },
});
