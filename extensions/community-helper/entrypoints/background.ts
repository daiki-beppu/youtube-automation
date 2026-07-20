import {
  checkServerCompatibility,
  fetchCommunityImage,
  fetchCommunityPosts,
} from "../../shared/api";
import { encodeAsset } from "../../shared/asset-transfer";
import { onMessage, sendMessage } from "../lib/messaging";

const COMMUNITY_POSTS_URL =
  /^https:\/\/www\.youtube\.com\/channel\/[^/]+\/posts(?:[?#].*)?$/u;

async function activeCommunityTabId(): Promise<number> {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (
    typeof tab?.id !== "number" ||
    !tab.url ||
    !COMMUNITY_POSTS_URL.test(tab.url)
  ) {
    throw new Error("YouTube のチャンネル投稿ページを開いてください");
  }
  return tab.id;
}

export default defineBackground(() => {
  console.info("[community-helper] background service worker started");

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
  onMessage("run", async ({ data }) => {
    await sendMessage("run", data, await activeCommunityTabId());
  });
  onMessage("stop", async () => {
    await sendMessage("stop", undefined, await activeCommunityTabId());
  });
  onMessage("contentProgress", ({ data }) => sendMessage("progress", data));
  onMessage("contentError", ({ data }) => sendMessage("error", data));
});
