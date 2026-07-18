// manifest は `wxt.config.ts` から自動生成されるため、権限宣言を import 可能な
// 単一定数に切り出し、wxt.config.ts はこの定数を参照する。これにより未使用権限の
// 混入を機械的に防ぐ（旧 `tests/test_suno_extension_manifest.py` の最小権限契約を移管）。
//
// 契約 (#1146 で `downloads`、#1251 で `debugger`、content script 自己復旧で `scripting` を追加):
//   - storage: chrome.storage.local（サーバー URL / resume state / overlay state 保存）
//   - activeTab: 現在タブの content script 注入
//   - downloads: Suno playlist の ZIP 一括ダウンロード完了を chrome.downloads API で監視する (#1146)
//   - debugger: Suno の isTrusted チェックを通す trusted Cmd+P dispatch (#1251)
//   - scripting: Chrome が静的 content script 登録を取りこぼしたときの Suno タブへの明示再注入
export const MANIFEST_PERMISSIONS = [
  "storage",
  "activeTab",
  "downloads",
  "debugger",
  "scripting",
] as const;
