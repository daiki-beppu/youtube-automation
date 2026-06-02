"use strict";

// Manifest V3 service worker。
// popup ⇄ content script は chrome.tabs.sendMessage で直接やり取りするため、
// 本 worker は拡張ライフサイクルのログのみを担う。
chrome.runtime.onInstalled.addListener((details) => {
  console.info(`[suno-helper] installed/updated: ${details.reason}`);
});
