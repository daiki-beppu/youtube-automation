import { onMessage, sendMessage } from "../lib/messaging";

async function activeStudioTabId(): Promise<number> {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (
    typeof tab?.id !== "number" ||
    !tab.url?.startsWith("https://studio.youtube.com/")
  ) {
    throw new Error("YouTube Studio のアクティブなタブを開いてください");
  }
  return tab.id;
}

export default defineBackground(() => {
  console.info("[community-helper] background service worker started");

  onMessage("checkCompatibility", async ({ data }) =>
    sendMessage("checkCompatibility", data, await activeStudioTabId())
  );
  onMessage("run", async ({ data }) => {
    await sendMessage("run", data, await activeStudioTabId());
  });
  onMessage("stop", async () => {
    await sendMessage("stop", undefined, await activeStudioTabId());
  });
  onMessage("contentProgress", ({ data }) => sendMessage("progress", data));
});
