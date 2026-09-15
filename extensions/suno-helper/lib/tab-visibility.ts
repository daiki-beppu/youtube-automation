export const SUNO_TAB_VISIBLE_MESSAGE =
  "Suno のタブを表示中にしてください。背面タブでは Playlist 操作が失敗することがあります。";

/**
 * document を持たない実行環境（node 環境の unit test harness 等）では可視扱いにする。
 * 実タブでは常に document.visibilityState をそのまま返す。
 */
export function currentTabVisibility(): DocumentVisibilityState {
  if (typeof document === "undefined") {
    return "visible";
  }
  return document.visibilityState;
}

export function requireVisibleSunoTab(
  visibilityState: DocumentVisibilityState
): string | null {
  return visibilityState === "visible" ? null : SUNO_TAB_VISIBLE_MESSAGE;
}
