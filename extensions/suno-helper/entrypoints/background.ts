// Manifest V3 service worker。
// popup ⇄ content script は @webext-core/messaging (tabs.sendMessage / runtime.sendMessage)
// で直接やり取りするため、本 worker は拡張ライフサイクルのログのみを担う。
export default defineBackground(() => {
  browser.runtime.onInstalled.addListener((details) => {
    console.info(`[suno-helper] installed/updated: ${details.reason}`);
  });
});
