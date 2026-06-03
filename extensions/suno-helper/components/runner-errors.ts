// useSunoRunner のエラー整形ヘルパ純関数（テスタビリティのため wxt 依存を排して分離）。
// 拡張をリロードした後 Suno タブをハードリロードしないと出る Chrome 標準エラー
// (`Could not establish connection. Receiving end does not exist.`) を検知して、
// popup の案内に対処法（⌘+Shift+R）を含める。

/**
 * content script 未注入の典型エラーを検知する。
 * 拡張をリロードした後に Suno タブをハードリロードしないと、古い content script が落ちた
 * まま新しい script が注入されず、popup → tab の sendMessage が
 * `Could not establish connection. Receiving end does not exist.` で失敗する。
 */
export function isContentScriptMissingError(message: string): boolean {
  return /receiving end does not exist|could not establish connection/i.test(message);
}

export function formatRunError(message: string): string {
  if (isContentScriptMissingError(message)) {
    return `開始失敗: ${message}\nSuno タブをハードリロード (⌘+Shift+R / Ctrl+Shift+R) してから再度実行してください。`;
  }
  return `開始失敗: ${message}\nSuno の Custom Mode 画面を開いた状態で実行してください。`;
}

export function formatStopError(message: string): string {
  if (isContentScriptMissingError(message)) {
    return `停止リクエスト失敗: ${message}\nSuno タブをハードリロード (⌘+Shift+R / Ctrl+Shift+R) してから再度実行してください。`;
  }
  return `停止リクエスト失敗: ${message}`;
}
