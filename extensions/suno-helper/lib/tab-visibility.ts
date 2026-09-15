export const SUNO_TAB_VISIBLE_MESSAGE =
  "Suno のタブを表示中にしてください。背面タブでは Playlist 操作が失敗することがあります。";

export function requireVisibleSunoTab(
  visibilityState: DocumentVisibilityState
): string | null {
  return visibilityState === "visible" ? null : SUNO_TAB_VISIBLE_MESSAGE;
}
