"use strict";

// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行。
// Suno の DOM は変わりうるため、セレクタはこの 1 箇所に集約する（壊れたら README 参照で更新）。
const { MSG, PHASE } = globalThis.SUNO_HELPER;

const SELECTORS = {
  // Style / Lyrics は textarea。placeholder で判別し、見つからなければ表示順で fallback。
  textareas: "textarea",
  stylePlaceholder: /style|genre|描述|スタイル/i,
  lyricsPlaceholder: /lyric|歌詞|歌词/i,
  // Generate ボタン: ラベルが "Create" / "Generate"。
  generateLabel: /^(create|generate|生成)$/i,
  // reCAPTCHA / challenge の兆候。
  recaptcha: 'iframe[src*="recaptcha"], iframe[title*="recaptcha" i], iframe[src*="hcaptcha"]',
};

const GENERATE_TIMEOUT_MS = 180000; // 1 曲の生成完了待ち上限
const POLL_INTERVAL_MS = 1000;
const SETTLE_MS = 1500; // 注入後・クリック後の安定化待ち

let aborted = false;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function progress(payload) {
  chrome.runtime.sendMessage({ type: MSG.PROGRESS, ...payload });
}

// React 互換のネイティブ値セット + input/change イベント発火。
function setNativeValue(el, value) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function detectRecaptcha() {
  return document.querySelector(SELECTORS.recaptcha) !== null;
}

// Style / Lyrics の textarea を解決する。見つからなければ throw（fail-loud）。
function resolveFields() {
  const areas = Array.from(document.querySelectorAll(SELECTORS.textareas)).filter(
    (el) => el.offsetParent !== null,
  );
  if (areas.length === 0) {
    throw new Error("textarea が見つかりません。Suno の Custom Mode 画面を開いてください。");
  }

  const byPlaceholder = (re) => areas.find((el) => re.test(el.placeholder || el.getAttribute("aria-label") || ""));
  const style = byPlaceholder(SELECTORS.stylePlaceholder) || areas[0];
  const lyrics = byPlaceholder(SELECTORS.lyricsPlaceholder) || (areas.length > 1 ? areas[1] : null);

  return { style, lyrics };
}

function resolveGenerateButton() {
  const buttons = Array.from(document.querySelectorAll("button")).filter((el) => el.offsetParent !== null);
  const btn = buttons.find((el) => SELECTORS.generateLabel.test((el.textContent || "").trim()));
  if (!btn) {
    throw new Error("Generate ボタンが見つかりません。Suno の UI 変更の可能性があります。");
  }
  return btn;
}

// クリック後、ボタンが一旦 disabled になり再度 enabled に戻るまで（= 生成完了）待つ。
async function waitForGeneration(button) {
  const deadline = Date.now() + GENERATE_TIMEOUT_MS;
  // disabled に変わるのを少し待つ（生成開始の検知）
  await sleep(SETTLE_MS);
  while (Date.now() < deadline) {
    if (aborted) return;
    if (detectRecaptcha()) {
      throw new Error("reCAPTCHA を検知しました。手動で解決してから再開してください。");
    }
    if (!button.disabled && button.getAttribute("aria-disabled") !== "true") {
      return;
    }
    await sleep(POLL_INTERVAL_MS);
  }
  throw new Error("生成完了の検知がタイムアウトしました。");
}

async function injectAndGenerate(entry, index, total) {
  const { style, lyrics } = resolveFields();
  setNativeValue(style, entry.style);
  if (entry.lyrics) {
    // 歌詞があるのに Lyrics 欄が見つからないのは設定不整合。silent に飛ばさず停止する。
    if (!lyrics) {
      throw new Error("Lyrics 欄が見つかりません。Instrumental OFF（Custom Mode）になっているか確認してください。");
    }
    setNativeValue(lyrics, entry.lyrics);
  }
  await sleep(SETTLE_MS);

  if (detectRecaptcha()) {
    throw new Error("reCAPTCHA を検知しました。手動で解決してから再開してください。");
  }

  const button = resolveGenerateButton();
  button.click();
  // Generate 押下後は最大 GENERATE_TIMEOUT_MS の生成完了待ちに入る。注入中と区別して表示する。
  progress({ phase: PHASE.GENERATING, index, total });
  await waitForGeneration(button);
}

async function runAll(entries) {
  const total = entries.length;
  for (let i = 0; i < total; i++) {
    if (aborted) {
      progress({ phase: PHASE.STOPPED, index: i, total });
      return;
    }
    try {
      progress({ phase: PHASE.INJECTING, index: i, total });
      await injectAndGenerate(entries[i], i, total);
      if (aborted) {
        progress({ phase: PHASE.STOPPED, index: i, total });
        return;
      }
      progress({ phase: PHASE.DONE, index: i, total });
    } catch (err) {
      progress({ phase: PHASE.ERROR, index: i, total, message: err.message });
      return;
    }
  }
  progress({ phase: PHASE.FINISHED, total });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === MSG.RUN) {
    aborted = false;
    runAll(msg.entries);
    sendResponse({ ok: true });
  } else if (msg.type === MSG.STOP) {
    aborted = true;
    sendResponse({ ok: true });
  }
  return false;
});
