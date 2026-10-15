/**
 * overlay の hit 領域を実 UI だけへ限定する (#5227)。
 * WXT が overlay position で生成する shadow host はページ側へ 0 サイズで置かれるが、
 * shadow 内の html / body コンテナや今後追加される装飾レイヤが pointer event を
 * 受けると、その直下にある Suno 側 UI（コンテキストメニュー等）へクリックが届かない。
 * host とコンテナを透過 (`pointer-events: none`) にし、panel 側 (OverlayShell の
 * Card) だけが `pointer-events: auto` で event を受け取る構成にする。
 */
export function scopeOverlayPointerEvents(
  host: HTMLElement | undefined,
  uiContainer: HTMLElement | undefined
): void {
  if (host) host.style.pointerEvents = "none";
  if (uiContainer) {
    uiContainer.style.pointerEvents = "none";
    uiContainer.parentElement?.style.setProperty("pointer-events", "none");
  }
}
