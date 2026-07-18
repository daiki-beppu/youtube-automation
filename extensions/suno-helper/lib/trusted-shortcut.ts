export async function sendTrustedCmdP(
  tabId: number,
  isMac: boolean
): Promise<void> {
  const modifiers = isMac ? 4 : 2; // 4=Meta, 2=Ctrl
  const target: chrome.debugger.Debuggee = { tabId };
  try {
    await chrome.debugger.attach(target, "1.3");
    try {
      await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
        type: "rawKeyDown",
        modifiers,
        key: "p",
        code: "KeyP",
        windowsVirtualKeyCode: 80,
        nativeVirtualKeyCode: 80,
      });
      await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
        type: "keyUp",
        modifiers,
        key: "p",
        code: "KeyP",
        windowsVirtualKeyCode: 80,
        nativeVirtualKeyCode: 80,
      });
    } finally {
      await chrome.debugger.detach(target);
    }
  } catch (err) {
    console.warn("[suno-helper] sendTrustedCmdP failed:", err);
    throw err;
  }
}
