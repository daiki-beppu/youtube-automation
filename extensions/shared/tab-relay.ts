interface TabMessageSender {
  tab?: {
    id?: number;
  };
}

export function senderTabId(sender: TabMessageSender): number | null {
  return typeof sender.tab?.id === "number" ? sender.tab.id : null;
}

/** Reject messages that cannot be safely scoped back to their source tab. */
export function requireSenderTabId(
  sender: TabMessageSender,
  messageType: string
): number {
  const tabId = senderTabId(sender);
  if (tabId === null) {
    throw new Error(`${messageType}: 送信元タブが特定できません`);
  }
  return tabId;
}
