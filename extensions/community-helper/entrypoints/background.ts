import {
  checkServerCompatibility,
  fetchCommunityImage,
  fetchCommunityPosts,
} from "../../shared/api";
import { encodeAsset } from "../../shared/asset-transfer";
import { requireSenderTabId } from "../../shared/tab-relay";
import { onMessage, sendMessage } from "../lib/messaging";

export default defineBackground(() => {
  console.info("[community-helper] background service worker started");

  browser.action.onClicked.addListener((tab) => {
    if (typeof tab.id !== "number") {
      return;
    }
    void sendMessage("toggleOverlay", undefined, tab.id).catch(
      (error: unknown) => {
        console.warn("[community-helper] overlay toggle relay failed:", error);
      }
    );
  });

  onMessage("checkCompatibility", ({ data }) =>
    checkServerCompatibility(data.baseUrl, data.extensionVersion)
  );
  onMessage("fetchCommunityPosts", ({ data }) =>
    fetchCommunityPosts(data.baseUrl)
  );
  onMessage("fetchCommunityImage", async ({ data }) => {
    const image = await fetchCommunityImage(data.baseUrl, data.index);
    return encodeAsset(`community-post-${data.index + 1}`, image);
  });
  onMessage("run", ({ data, sender }) =>
    sendMessage("run", data, requireSenderTabId(sender, "run"))
  );
  onMessage("stop", ({ sender }) =>
    sendMessage("stop", undefined, requireSenderTabId(sender, "stop"))
  );
  onMessage("contentProgress", ({ data, sender }) =>
    sendMessage("progress", data, requireSenderTabId(sender, "contentProgress"))
  );
  onMessage("contentError", ({ data, sender }) =>
    sendMessage("error", data, requireSenderTabId(sender, "contentError"))
  );
});
