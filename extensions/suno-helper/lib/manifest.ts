// manifest は `wxt.config.ts` から自動生成されるため、権限宣言を import 可能な
// 単一定数に切り出し、wxt.config.ts はこの定数を参照する。これにより未使用権限の
// 混入を機械的に防ぐ（旧 `tests/test_suno_extension_manifest.py` の最小権限契約を移管）。
//
// 契約 (#893 で `tabs` を追加): chrome.storage.local + activeTab + tabs。
// `tabs` は自動 POST trigger（background が `https://suno.com/me` を bg tab で開閉し
// playlist を scrape → POST する、追加要件 A）で `browser.tabs.create / remove` を
// 呼ぶために必要。それ以外の広域権限（history / bookmarks / cookies 等）は混入させない。
export const MANIFEST_PERMISSIONS = ["storage", "activeTab", "tabs"] as const;
