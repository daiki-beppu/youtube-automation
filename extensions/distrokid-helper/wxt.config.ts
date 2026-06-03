import { defineConfig } from "wxt";

// WXT 設定。最小権限で Manifest V3 を生成する（要件 #2）。
export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  manifest: {
    name: "DistroKid Helper",
    description: "DistroKid 登録フォームに静的プロファイル + 動的データを自動入力する",
    // 最小権限: storage（サーバー URL 永続化） + activeTab（注入対象タブ）。tabs は含めない。
    permissions: ["storage", "activeTab"],
    // 注入対象を distrokid.com 系に限定する。
    host_permissions: ["*://*.distrokid.com/*"],
  },
});
