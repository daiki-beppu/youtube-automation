// overlay (content script) ⇄ runner (content script) の background 中継ロジック (#892)。
//
// overlay と runner は同一 Suno タブ上の別 content script だが、content script 同士は直接 messaging
// できない（@webext-core/messaging: "You cannot message between tabs directly. It must go through the
// background script."）。runtime.sendMessage は他 content script へ配送されず、tabs.sendMessage は
// content script から呼べない（`browser.tabs` 未提供）。そのため background が overlay の no-tabId
// メッセージを受け、送信元と同一タブ (sender.tab.id) へ tabs.sendMessage で転送する。
//
// 中継対象は content script 起源（sender.tab.id を持つ）のメッセージに限る。tab を持たない送信元
// （background 自身 / 廃止済み popup 等）を素通しすると no-tabId のまま runtime へ再送して無限ループに
// なるため、tab を持たないものは null を返して転送しない。

/** background 中継に必要な sender の最小形（webextension-polyfill Runtime.MessageSender の部分形）。 */
export interface RelaySender {
  tab?: { id?: number };
}

/**
 * メッセージの中継先タブ id を返す。content script 起源（tab.id を持つ）なら同一タブへ転送するため
 * その tab.id を、そうでなければ null（転送しない＝loop 防止）を返す。
 */
export function relayTabId(sender: RelaySender): number | null {
  return typeof sender.tab?.id === "number" ? sender.tab.id : null;
}

/**
 * 応答が必須な中継（run / stop / queryProgress）の中継先タブ id を解決する。content script 起源で
 * なければ転送先が無いため fail-loud で throw する（握りつぶさない）。progress のような no-op 折返しは
 * 中継先不在を許容するため本関数ではなく `relayTabId` を直接使う。
 * @param action エラー文言に埋め込むメッセージ種別。
 */
export function requireRelayTab(sender: RelaySender, action: string): number {
  const tabId = relayTabId(sender);
  if (tabId === null) {
    throw new Error(`${action} の中継先タブを特定できません（content script 起源ではありません）。`);
  }
  return tabId;
}
