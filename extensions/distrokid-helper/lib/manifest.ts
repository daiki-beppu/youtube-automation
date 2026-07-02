// manifest は `wxt.config.ts` から自動生成されるため、権限宣言を import 可能な
// 単一定数に切り出し、wxt.config.ts はこの定数を参照する。これにより未使用権限の
// 混入を機械的に防ぐ（suno-helper の lib/manifest.ts と同型の shell、ADR-0016）。
//
// 契約:
//   - storage: chrome.storage.local（サーバー URL 永続化）
//   - activeTab: 注入対象タブへの content script 注入
//   - tabs は含めない（suno-helper と異なり bg tab 操作を行わない）
export const MANIFEST_PERMISSIONS = ["storage", "activeTab"] as const;

// 注入対象を distrokid.com 系に限定する。release.json / asset の fetch はすべて
// popup（chrome-extension:// origin）で行う設計のため、サーバー向け host permission
// は追加しない（extensions/distrokid-helper/README.md「popup fetch 構成」参照）。
export const MANIFEST_HOST_PERMISSIONS = ["*://*.distrokid.com/*"] as const;
