"use strict";

const { STORAGE_KEY, PROMPTS_ROUTE, DEFAULT_URL, MSG, PHASE } = globalThis.SUNO_HELPER;

const urlInput = document.getElementById("server-url");
const fetchBtn = document.getElementById("fetch-btn");
const runBtn = document.getElementById("run-btn");
const stopBtn = document.getElementById("stop-btn");
const statusEl = document.getElementById("status");
const listEl = document.getElementById("pattern-list");

let entries = [];

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function renderList() {
  listEl.replaceChildren();
  for (const entry of entries) {
    const li = document.createElement("li");
    li.textContent = entry.name;
    listEl.appendChild(li);
  }
}

function markItem(index, className) {
  const items = listEl.querySelectorAll("li");
  items.forEach((li) => li.classList.remove("active"));
  const li = items[index];
  if (li) li.classList.add(className);
}

async function activeTabId() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) throw new Error("アクティブなタブが見つかりません。");
  return tab.id;
}

async function loadStoredUrl() {
  const stored = await chrome.storage.local.get(STORAGE_KEY);
  urlInput.value = stored[STORAGE_KEY] || DEFAULT_URL;
}

fetchBtn.addEventListener("click", async () => {
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("サーバー URL を入力してください。", true);
    return;
  }
  await chrome.storage.local.set({ [STORAGE_KEY]: url });
  setStatus("取得中…");
  try {
    const resp = await fetch(`${url}${PROMPTS_ROUTE}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!Array.isArray(data) || data.length === 0) {
      throw new Error("空、または配列ではない JSON が返りました。");
    }
    entries = data;
    renderList();
    runBtn.disabled = false;
    setStatus(`${entries.length} パターンを取得しました。`);
  } catch (err) {
    entries = [];
    renderList();
    runBtn.disabled = true;
    setStatus(`取得失敗: ${err.message}\nyt-collection-serve が起動しているか確認してください。`, true);
  }
});

runBtn.addEventListener("click", async () => {
  if (entries.length === 0) return;
  try {
    const tabId = await activeTabId();
    await chrome.tabs.sendMessage(tabId, { type: MSG.RUN, entries });
    runBtn.disabled = true;
    stopBtn.disabled = false;
    setStatus("連続実行を開始しました。");
  } catch (err) {
    setStatus(`開始失敗: ${err.message}\nSuno の Custom Mode 画面を開いた状態で実行してください。`, true);
  }
});

stopBtn.addEventListener("click", async () => {
  try {
    const tabId = await activeTabId();
    await chrome.tabs.sendMessage(tabId, { type: MSG.STOP });
  } catch (err) {
    setStatus(`停止リクエスト失敗: ${err.message}`, true);
  }
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== MSG.PROGRESS) return;
  const { phase, index, total, message } = msg;
  switch (phase) {
    case PHASE.INJECTING:
      markItem(index, "active");
      setStatus(`[${index + 1}/${total}] 注入中: ${entries[index]?.name ?? ""}`);
      break;
    case PHASE.GENERATING:
      setStatus(`[${index + 1}/${total}] 生成待ち…`);
      break;
    case PHASE.DONE:
      markItem(index, "done");
      break;
    case PHASE.FINISHED:
      setStatus(`完了: ${total} パターンを実行しました。`);
      runBtn.disabled = false;
      stopBtn.disabled = true;
      break;
    case PHASE.STOPPED:
      setStatus("停止しました。手動で続行できます。", true);
      runBtn.disabled = false;
      stopBtn.disabled = true;
      break;
    case PHASE.ERROR:
      setStatus(`中断: ${message}`, true);
      runBtn.disabled = false;
      stopBtn.disabled = true;
      break;
  }
});

loadStoredUrl();
