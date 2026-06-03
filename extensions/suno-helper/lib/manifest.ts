// manifest は `wxt.config.ts` から自動生成されるため、権限宣言を import 可能な
// 単一定数に切り出し、wxt.config.ts はこの定数を参照する。これにより未使用権限の
// 混入を機械的に防ぐ（旧 `tests/test_suno_extension_manifest.py` の最小権限契約を移管）。
//
// 契約: chrome.storage.local + activeTab のみ。`tabs` は不要
// (chrome.tabs.query が返す tab.id / chrome.tabs.sendMessage は特権プロパティを
//  参照しないため activeTab で成立)。
export const MANIFEST_PERMISSIONS = ["storage", "activeTab"] as const;
