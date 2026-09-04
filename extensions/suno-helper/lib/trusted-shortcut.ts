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

export async function sendTrustedClick(
  tabId: number,
  x: number,
  y: number
): Promise<void> {
  const target: chrome.debugger.Debuggee = { tabId };
  try {
    await chrome.debugger.attach(target, "1.3");
    try {
      const point = {
        x,
        y,
      } as const;
      await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
        ...point,
        type: "mouseMoved",
        button: "none",
        buttons: 0,
      });
      await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
        ...point,
        type: "mousePressed",
        button: "left",
        buttons: 1,
        clickCount: 1,
      });
      await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
        ...point,
        type: "mouseReleased",
        button: "left",
        buttons: 0,
        clickCount: 1,
      });
    } finally {
      await chrome.debugger.detach(target);
    }
  } catch (err) {
    console.warn("[suno-helper] sendTrustedClick failed:", err);
    throw err;
  }
}
