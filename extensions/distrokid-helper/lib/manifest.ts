// manifest は wxt.config.ts から自動生成されるため、権限宣言を import 可能な
// 単一定数に切り出し、wxt.config.ts はこの定数を参照する。
// 契約: storage（サーバー URL 永続化）+ activeTab（注入対象タブ）。
// tabs は含めない（distrokid-helper は bg tab 操作を行わない）。
export const MANIFEST_PERMISSIONS = ["storage", "activeTab"] as const;
