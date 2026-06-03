// service worker。型付きチャンネルは popup ↔ content 間の直接通信で完結するため、
// ここではライフサイクルログのみを担う（suno-helper の background と対称）。

export default defineBackground(() => {
  console.info("[distrokid-helper] background service worker started");
});
