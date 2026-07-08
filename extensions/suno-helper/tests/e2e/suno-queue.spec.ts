// 要件 (#816 → #866 で再実装): Suno 生成キュー監視と collection 選択 UI の E2E スモーク (実 Suno 非依存)。
//
// content script は manifest の matches (`https://suno.com/*`) でしか注入されず、Playwright の
// page.evaluate に渡す関数はシリアライズされブラウザ文脈で実行されるため本番 `shared/dom.ts` を
// 直接 import できない (既存 suno-inject.spec.ts と同じ制約)。よってここでは
// findCardRoot / isClipGenerating / getInFlightClipCount / waitForQueueSlot と同手法を inline 再現し、
// 「11 件目は queue 待ちで停止 → 1 完了で投入される」が実ブラウザの layout 上で成立することを示す。
// #866: Suno が clip-row testid と svg.animate-spin を撤去したため、in-flight マーカーを
// `button[aria-label="Remix clip"]` の disabled に切り替えた新 DOM 構造で検証する。
// 本番関数自体の回帰は jsdom 上で `shared/dom.ts` を import する unit (`tests/queue.test.ts`) が担う。
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { CLIPS_PER_REQUEST, MAX_INFLIGHT_REQUESTS, PHASE } from "../../../shared/constants";
import { pickInitialCollectionId, type CollectionSummary, type PromptEntry } from "../../../shared/api";
import { submitQueueEntries, waitForSubmittedClipsComplete } from "../../lib/queue-runner";
import type { QueueSubmissionOptions, SubmittedClipCompletionOptions } from "../../lib/queue-runner";
import { buildRunPayload } from "../../lib/run-overrides";

// clip card を 20 枚 (= 10 リクエスト in-flight = 上限) 並べた Suno 生成キューの mock。
// 各 card は Select clip / Remix clip / Edit title を 1 つずつ持ち、生成中は Remix btn を disabled にする。
const MOCK_QUEUE_HTML = `<!doctype html>
<html>
  <body>
    <div id="grid">
      ${Array.from({ length: 20 })
        .map(
          (_, i) =>
            `<div class="clip-card" id="clip-${i}" style="width:200px;height:60px">` +
            `<button aria-label="Select clip"></button>` +
            `<button aria-label="Remix clip" disabled></button>` +
            `<button aria-label="Edit title"></button>` +
            `</div>`,
        )
        .join("\n")}
    </div>
  </body>
</html>`;

const MOCK_ALT_VIEW_QUEUE_HTML = `<!doctype html>
<html>
  <body>
    <section id="waveform" style="width:240px;height:180px;overflow:auto">
      <article id="waveform-0" aria-busy="true" style="width:200px;height:60px">
        <button aria-label="Select clip"></button>
      </article>
      <article id="waveform-1" style="width:200px;height:60px">
        <button aria-label="Select clip"></button>
        <div role="progressbar"></div>
      </article>
    </section>
    <section id="grid" style="width:240px;height:180px;overflow:auto">
    </section>
  </body>
</html>`;

const MOCK_ALT_VIEW_UNCOUNTABLE_HTML = `<!doctype html>
<html>
  <body>
    <section id="grid" style="width:240px;height:180px;overflow:auto">
      <article id="grid-0" style="width:200px;height:60px">
        <button aria-label="Select clip"></button>
      </article>
    </section>
  </body>
</html>`;

type InFlightCounterWindow = Window & {
  __sunoHelperE2EGetInFlightClipCount: () => number;
};

function makePromptEntries(count: number): PromptEntry[] {
  return Array.from({ length: count }, (_, i) => ({
    name: `queue-entry-${i + 1}`,
    style: `style ${i + 1}`,
    lyrics: `lyrics ${i + 1}`,
  }));
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function makeQueueSubmissionOptions(input: {
  entries: PromptEntry[];
  submittedIndexes: number[];
  submittedClipIds: string[];
  waitForQueueSlot?: QueueSubmissionOptions["waitForQueueSlot"];
}): QueueSubmissionOptions {
  const waitForQueueSlot = input.waitForQueueSlot ?? (async () => {});
  return {
    entries: input.entries,
    order: input.entries.map((_, i) => i),
    total: input.entries.length,
    maxGeneratingClips: MAX_INFLIGHT_REQUESTS * CLIPS_PER_REQUEST,
    preset: {
      interCreateDelayMs: 0,
      jitterMs: 0,
      maxInjectRetry: 0,
      injectAckTimeoutMs: 50,
      maxEntryRetry: 0,
    },
    isAborted: () => false,
    isEntrySubmitted: (index) => input.submittedIndexes.includes(index),
    getSubmittedIds: () => [...input.submittedClipIds],
    getSubmissionCount: () => input.submittedIndexes.length,
    getDomInFlightCount: () => input.submittedClipIds.length,
    hasObservedAnyTraffic: () => true,
    getLastChangeAt: () => Date.now(),
    currentInFlightCount: () => input.submittedClipIds.length,
    emitProgress: () => {},
    submitEntryToQueue: async (_entry, index) => {
      input.submittedIndexes.push(index);
      input.submittedClipIds.push(`clip-${index}-a`, `clip-${index}-b`);
    },
    waitForAck: async () => true,
    waitForQueueSlot,
    persistInterruptState: () => {
      throw new Error("interrupt state should not be persisted in the happy-path E2E test");
    },
    applyJitter: (baseMs) => baseMs,
    abortableSleep: async () => {},
    sleep: async () => {},
  };
}

function getInFlightClipCountInPage(): number {
  const REMIX_BTN_SELECTOR = 'button[aria-label="Remix clip"]';
  const SELECT_CLIP_SELECTOR = 'button[aria-label="Select clip"]';
  const DESELECT_CLIP_SELECTOR = 'button[aria-label="Deselect clip"]';
  const EDIT_TITLE_SELECTOR = 'button[aria-label="Edit title"]';
  const isVisible = (el: HTMLElement): boolean => {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    let node: HTMLElement | null = el;
    while (node) {
      const style = getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
        return false;
      }
      node = node.parentElement;
    }
    return true;
  };
  const isDocumentRoot = (root: HTMLElement): boolean => root === document.body || root === document.documentElement;
  const hasExactlyOne = (root: HTMLElement, selector: string): boolean => root.querySelectorAll(selector).length === 1;
  const hasListActions = (root: HTMLElement): boolean =>
    hasExactlyOne(root, SELECT_CLIP_SELECTOR) &&
    hasExactlyOne(root, REMIX_BTN_SELECTOR) &&
    hasExactlyOne(root, EDIT_TITLE_SELECTOR);
  const hasWaveformActions = (root: HTMLElement): boolean =>
    hasExactlyOne(root, SELECT_CLIP_SELECTOR) && hasExactlyOne(root, REMIX_BTN_SELECTOR);
  const hasGridActions = (root: HTMLElement): boolean => hasExactlyOne(root, REMIX_BTN_SELECTOR);
  const isAlternateViewCardBoundary = (root: HTMLElement): boolean => root.matches("article");
  const findCardRoot = (anchor: HTMLElement): HTMLElement => {
    let current: HTMLElement | null = anchor.parentElement;
    let hiddenCandidate: HTMLElement | null = null;
    while (current) {
      if (
        !isDocumentRoot(current) &&
        (hasListActions(current) ||
          (isAlternateViewCardBoundary(current) && (hasWaveformActions(current) || hasGridActions(current))))
      ) {
        if (isVisible(current)) return current;
        hiddenCandidate = current;
      }
      current = current.parentElement;
    }
    if (hiddenCandidate) return hiddenCandidate;
    throw new Error("clip card root を解決できません。");
  };
  const hasAlternateInFlightSignal = (card: HTMLElement): boolean =>
    isVisible(card) &&
    (card.matches('[aria-busy="true"]') || card.querySelector('[aria-busy="true"], [role="progressbar"]') !== null);
  const hasClipIdentity = (card: HTMLElement): boolean =>
    card.querySelector(
      `${SELECT_CLIP_SELECTOR}, ${DESELECT_CLIP_SELECTOR}, ${REMIX_BTN_SELECTOR}, ${EDIT_TITLE_SELECTOR}`,
    ) !== null;
  const hasCountSignal = (card: HTMLElement): boolean =>
    card.querySelector(REMIX_BTN_SELECTOR) !== null || hasAlternateInFlightSignal(card);
  const findArticleCardRoot = (anchor: HTMLElement): HTMLElement | null => {
    const article = anchor.closest<HTMLElement>("article");
    return article && !isDocumentRoot(article) ? article : null;
  };
  const findClipCandidateRoot = (anchor: HTMLElement): HTMLElement | null => {
    const article = findArticleCardRoot(anchor);
    if (article && hasClipIdentity(article)) return article;
    let current = anchor.parentElement;
    while (current) {
      if (isDocumentRoot(current)) return null;
      if (hasClipIdentity(current)) return current;
      current = current.parentElement;
    }
    return null;
  };
  const collectInFlightCandidates = (): {
    inFlightCards: Set<HTMLElement>;
    clipCandidates: Set<HTMLElement>;
    uncountableCandidates: Set<HTMLElement>;
  } => {
    const anchors = document.querySelectorAll<HTMLElement>(
      `${SELECT_CLIP_SELECTOR}, ${DESELECT_CLIP_SELECTOR}, ${REMIX_BTN_SELECTOR}, ${EDIT_TITLE_SELECTOR}, [aria-busy="true"], [role="progressbar"]`,
    );
    const inFlightCards = new Set<HTMLElement>();
    const clipCandidates = new Set<HTMLElement>();
    const uncountableCandidates = new Set<HTMLElement>();
    for (const anchor of anchors) {
      const card = findClipCandidateRoot(anchor);
      if (!card || !isVisible(card) || !hasClipIdentity(card)) continue;
      clipCandidates.add(card);
      if (!hasCountSignal(card)) {
        uncountableCandidates.add(card);
        continue;
      }
      if (hasAlternateInFlightSignal(card)) inFlightCards.add(card);
    }
    return { inFlightCards, clipCandidates, uncountableCandidates };
  };
  const detectSunoViewMode = (): "grid" | "list" | "unknown" | "waveform" => {
    const triggers = Array.from(
      document.querySelectorAll<HTMLElement>(
        'button[aria-haspopup], button[aria-expanded], [role="button"][aria-haspopup], [role="button"][aria-expanded]',
      ),
    );
    const modes = new Set<"grid" | "list" | "waveform">();
    for (const trigger of triggers) {
      const tokens = (trigger.textContent ?? "")
        .toLowerCase()
        .replace(/[^a-z]+/g, " ")
        .split(/\s+/);
      if (tokens.includes("list")) modes.add("list");
      if (tokens.includes("waveform")) modes.add("waveform");
      if (tokens.includes("grid")) modes.add("grid");
    }
    return modes.size === 1 ? Array.from(modes)[0] : "unknown";
  };
  const isClipGenerating = (card: HTMLElement): boolean => {
    const remix = card.querySelector<HTMLButtonElement>(REMIX_BTN_SELECTOR);
    if (!remix) throw new Error("card 内に Remix btn が見つかりません。");
    return isVisible(card) && (remix.disabled || remix.getAttribute("aria-disabled") === "true");
  };
  const remixAnchors = document.querySelectorAll<HTMLButtonElement>(REMIX_BTN_SELECTOR);
  const cards = new Set<HTMLElement>();
  for (const anchor of remixAnchors) {
    const card = findCardRoot(anchor);
    if (isClipGenerating(card)) cards.add(card);
  }
  const candidates = collectInFlightCandidates();
  if (candidates.uncountableCandidates.size > 0) {
    throw new Error("clip 候補に in-flight 検知シグナルがありません。");
  }
  for (const card of candidates.inFlightCards) {
    cards.add(card);
  }
  if (remixAnchors.length === 0 && cards.size === 0) {
    if (candidates.clipCandidates.size === 0 && detectSunoViewMode() !== "unknown") return 0;
    throw new Error("in-flight 検知シグナルと現在ビューが 0 件です。");
  }
  return cards.size;
}

async function installInFlightCounter(page: Page): Promise<void> {
  await page.addScriptTag({
    content: `window.__sunoHelperE2EGetInFlightClipCount = (${getInFlightClipCountInPage.toString()});`,
  });
}

function getInstalledInFlightClipCountInPage(): number {
  return (window as unknown as InFlightCounterWindow).__sunoHelperE2EGetInFlightClipCount();
}

test("production payload と queue runner は queue mode で生成完了待ちなしに次 entry を投入する", async () => {
  const entries = makePromptEntries(2);
  const payload = buildRunPayload({
    entries,
    playlistName: "Queue Smoke",
    range: undefined,
    collectionId: "queue-smoke",
    runMode: "queue",
    overrides: undefined,
  });
  const submittedIndexes: number[] = [];
  const submittedClipIds: string[] = [];
  const progress: string[] = [];
  const options = makeQueueSubmissionOptions({ entries, submittedIndexes, submittedClipIds });
  options.emitProgress = (value) => {
    if (value.phase === PHASE.SUBMITTED) {
      progress.push(`${value.phase}:${value.index}`);
    }
  };

  const result = await submitQueueEntries(options);

  expect(payload.runMode).toBe("queue");
  expect(result).toEqual({ completed: true, failedIndices: [] });
  expect(submittedIndexes).toEqual([0, 1]);
  expect(submittedClipIds).toEqual(["clip-0-a", "clip-0-b", "clip-1-a", "clip-1-b"]);
  expect(progress).toEqual([`${PHASE.SUBMITTED}:0`, `${PHASE.SUBMITTED}:1`]);
});

test("production queue runner は 10 request cap 到達中に 11 件目を投入しない", async () => {
  const entries = makePromptEntries(MAX_INFLIGHT_REQUESTS + 1);
  const submittedIndexes: number[] = [];
  const submittedClipIds: string[] = [];
  const eleventhSlot = deferred();
  const maxGeneratingClipArgs: number[] = [];
  const waitForQueueSlot: QueueSubmissionOptions["waitForQueueSlot"] = async (maxGeneratingClips) => {
    maxGeneratingClipArgs.push(maxGeneratingClips);
    if (maxGeneratingClipArgs.length === MAX_INFLIGHT_REQUESTS + 1) {
      await eleventhSlot.promise;
    }
  };
  const options = makeQueueSubmissionOptions({
    entries,
    submittedIndexes,
    submittedClipIds,
    waitForQueueSlot,
  });

  const pending = submitQueueEntries(options);

  await expect.poll(() => maxGeneratingClipArgs.length).toBe(MAX_INFLIGHT_REQUESTS + 1);
  expect(maxGeneratingClipArgs).toEqual(
    Array.from({ length: MAX_INFLIGHT_REQUESTS + 1 }, () => MAX_INFLIGHT_REQUESTS * CLIPS_PER_REQUEST),
  );
  expect(submittedIndexes).toEqual(Array.from({ length: MAX_INFLIGHT_REQUESTS }, (_, i) => i));

  eleventhSlot.resolve();
  await expect(pending).resolves.toEqual({ completed: true, failedIndices: [] });
  expect(submittedIndexes).toEqual(Array.from({ length: MAX_INFLIGHT_REQUESTS + 1 }, (_, i) => i));
});

test("production completion gate は resume 済み未完了 clip を playlist 前に feed poll 対象へ入れる", async () => {
  const previousSubmittedClipIds = ["previous-clip-a", "previous-clip-b"];
  const pendingClipIds = new Set(previousSubmittedClipIds);
  const feedPollStarted = deferred();
  const feedPollMayFinish = deferred();
  const feedPollRequests: string[][] = [];
  let playlistReached = false;
  const options: SubmittedClipCompletionOptions = {
    expectedClipCount: previousSubmittedClipIds.length,
    previousSubmittedClipIds,
    isAborted: () => false,
    getSubmittedIds: () => [],
    getPendingIdsByIds: (ids) => ids.filter((id) => pendingClipIds.has(id)),
    getPendingSubmittedIds: () => [],
    requestFeedPoll: async (ids) => {
      feedPollRequests.push([...ids]);
      feedPollStarted.resolve();
      await feedPollMayFinish.promise;
      pendingClipIds.clear();
    },
    abortableSleep: async () => {},
  };

  const pendingCompletion = waitForSubmittedClipsComplete(options).then(() => {
    playlistReached = true;
  });

  await feedPollStarted.promise;
  expect(feedPollRequests).toEqual([previousSubmittedClipIds]);
  expect(playlistReached).toBe(false);

  feedPollMayFinish.resolve();
  await pendingCompletion;
  expect(playlistReached).toBe(true);
});

test("11 件目は in-flight 上限 (20 clip) で待機し、1 clip 完了で投入が再開する", async ({ page }) => {
  await page.setContent(MOCK_QUEUE_HTML);
  await installInFlightCounter(page);

  const result = await page.evaluate(async () => {
    const REMIX_BTN_SELECTOR = 'button[aria-label="Remix clip"]';
    const getInFlightClipCount = () =>
      (window as unknown as InFlightCounterWindow).__sunoHelperE2EGetInFlightClipCount();
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const waitForQueueSlot = async (maxClips: number): Promise<void> => {
      const deadline = Date.now() + 5000;
      while (Date.now() < deadline) {
        if (getInFlightClipCount() < maxClips) return;
        await sleep(20);
      }
      throw new Error("queue slot 待ちがタイムアウトしました。");
    };

    const before = getInFlightClipCount();

    let resolved = false;
    const pending = waitForQueueSlot(20).then(() => {
      resolved = true;
    });

    // 上限のままでは投入を待つ (resolve しない)。
    await sleep(80);
    const blockedWhileFull = !resolved;

    // 1 clip 完了 (Remix btn enabled) → in-flight 19 < 20 → 投入再開。
    document.querySelector<HTMLButtonElement>(REMIX_BTN_SELECTOR)?.removeAttribute("disabled");
    await pending;

    return { before, blockedWhileFull, resolvedAfterFree: resolved, after: getInFlightClipCount() };
  });

  expect(result.before).toBe(20); // 10 リクエスト = 20 clip が in-flight (上限)
  expect(result.blockedWhileFull).toBe(true); // 上限の間は 11 件目を待たせる
  expect(result.resolvedAfterFree).toBe(true); // 1 完了で待機解除
  expect(result.after).toBe(19);
});

test("Waveform 風の Remix 0 DOM は明示的な生成中シグナルだけを in-flight として数える", async ({ page }) => {
  await page.setContent(MOCK_ALT_VIEW_QUEUE_HTML);
  await installInFlightCounter(page);

  const count = await page.evaluate(getInstalledInFlightClipCountInPage);
  const remixCount = await page.locator('button[aria-label="Remix clip"]').count();

  expect(remixCount).toBe(0);
  expect(count).toBe(2);
});

test("Grid 風の Remix 0 DOM は signal 欠落 clip 候補を fail-loud にする", async ({ page }) => {
  await page.setContent(MOCK_ALT_VIEW_UNCOUNTABLE_HTML);
  await installInFlightCounter(page);

  await expect(page.evaluate(getInstalledInFlightClipCountInPage)).rejects.toThrow(/in-flight 検知シグナル/);
});

// collection 選択ドロップダウン UI のスモーク。popup の React 実装は unpacked 拡張ロードを要するため、
// ここでは「fetchCollections の結果から <select> を populate し、needs_prompts を disabled、
// 初期値を最初の ready にする」契約を mock DOM で検証する (#1216)。
const MOCK_POPUP_HTML = `<!doctype html>
<html><body><select id="collection"></select></body></html>`;

test("collection ドロップダウンは populate され、needs_prompts は disabled・初期値は最初の有効 entry", async ({
  page,
}) => {
  await page.setContent(MOCK_POPUP_HTML);
  const collections: CollectionSummary[] = [
    { id: "c1", name: "midnight-mood", status: "needs_prompts", pattern_count: null, downloaded_count: 0 },
    { id: "c2", name: "sunset-drive", status: "ready", pattern_count: 12, downloaded_count: 0 },
    { id: "c3", name: "dawn-chorus", status: "downloaded", pattern_count: 8, downloaded_count: 8 },
  ];
  const initialId = pickInitialCollectionId(collections) ?? "";

  const result = await page.evaluate(
    ({ collections, initialId }) => {
      const select = document.getElementById("collection") as HTMLSelectElement;
      for (const c of collections) {
        const opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = c.name;
        opt.disabled = c.status === "needs_prompts"; // needs_prompts は選べない
        select.appendChild(opt);
      }
      select.value = initialId;

      return {
        optionCount: select.options.length,
        firstDisabled: select.options[0].disabled,
        secondDisabled: select.options[1].disabled,
        selectedValue: select.value,
      };
    },
    { collections, initialId },
  );

  expect(result.optionCount).toBe(3);
  expect(result.firstDisabled).toBe(true); // c1 (needs_prompts)
  expect(result.secondDisabled).toBe(false); // c2 (ready)
  expect(result.selectedValue).toBe("c2"); // 初期値 = 最初の ready entry
});

// #847: queue 上限エラー toast ([role="dialog"] + "Generation in progress") 検知中は、
// 空きスロットがあっても投入を止め、toast 消失後に再開する挙動を実ブラウザ layout 上で再現検証する。
// 本番 isQueueLimitErrorVisible / waitForQueueSlot の回帰は jsdom unit (tests/queue.test.ts) が担う。
const MOCK_TOAST_HTML = `<!doctype html>
<html>
  <body>
    <div id="grid">
      <div class="clip-card" id="clip-0" style="width:200px;height:60px">
        <button aria-label="Select clip"></button>
        <button aria-label="Remix clip"></button>
        <button aria-label="Edit title"></button>
      </div>
    </div>
    <div id="toast" role="dialog" style="width:360px;height:120px">
      <h3>Generation in progress</h3>
      <span>他の曲の生成が完了するまでお待ちいただき、その後もう一度お試しください。</span>
    </div>
  </body>
</html>`;

test("queue 上限 toast 検知中は空きスロットでも待機し、toast 消失で投入を再開する (#847)", async ({ page }) => {
  await page.setContent(MOCK_TOAST_HTML);
  await installInFlightCounter(page);

  const result = await page.evaluate(async () => {
    const isVisible = (el: HTMLElement): boolean => {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false;
      let node: HTMLElement | null = el;
      while (node) {
        const style = getComputedStyle(node);
        if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
          return false;
        }
        node = node.parentElement;
      }
      return true;
    };
    const getInFlightClipCount = () =>
      (window as unknown as InFlightCounterWindow).__sunoHelperE2EGetInFlightClipCount();
    const isQueueLimitErrorVisible = (): boolean =>
      Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]')).some(
        (el) => isVisible(el) && (el.textContent ?? "").toLowerCase().includes("generation in progress"),
      );
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const QUEUE_ERROR_WAIT_MS = 120; // テスト短縮した安全マージン
    const waitForQueueSlot = async (maxClips: number): Promise<void> => {
      const deadline = Date.now() + 5000;
      let sawToast = false;
      while (Date.now() < deadline) {
        if (isQueueLimitErrorVisible()) {
          sawToast = true;
          await sleep(20);
          continue;
        }
        if (sawToast) {
          await sleep(QUEUE_ERROR_WAIT_MS);
          sawToast = false;
          continue;
        }
        if (getInFlightClipCount() < maxClips) return;
        await sleep(20);
      }
      throw new Error("queue slot 待ちがタイムアウトしました。");
    };

    // 前提: スロットは空いている (in-flight 0 < 20) のに toast が出ている状況。
    const slotFreeButToastUp = getInFlightClipCount() < 20 && isQueueLimitErrorVisible();

    let resolved = false;
    const pending = waitForQueueSlot(20).then(() => {
      resolved = true;
    });

    await sleep(80);
    const blockedWhileToast = !resolved; // toast 中は空きでも投入を待つ

    document.getElementById("toast")?.remove(); // toast 消失
    await pending;

    return { slotFreeButToastUp, blockedWhileToast, resolvedAfterToastGone: resolved };
  });

  expect(result.slotFreeButToastUp).toBe(true); // スロットは空きなのに toast が出ている
  expect(result.blockedWhileToast).toBe(true); // toast 中は待機（誤投入しない）
  expect(result.resolvedAfterToastGone).toBe(true); // 消失で再開
});

// #847 受け入れ条件「停止押下後 3 秒以内にフロー停止」。固定 sleep を abortableSleep に置換することで
// 長い待機 (SETTLE_MS=1500 等) の途中でも中断できることを実ブラウザの real timer 上で再現検証する。
test("abortableSleep は中断フラグで長い待機の途中でも 3 秒以内に抜ける (#847)", async ({ page }) => {
  await page.setContent("<!doctype html><html><body></body></html>");

  const result = await page.evaluate(async () => {
    // 本番 abortableSleep と同じ「ms 経過 or 中断 の早い方で resolve、内部 poll で中断検知」を inline 再現。
    const abortableSleep = (ms: number, isAborted: () => boolean): Promise<void> =>
      new Promise((resolve) => {
        const poll = 50;
        const deadline = Date.now() + ms;
        const tick = () => {
          if (isAborted() || Date.now() >= deadline) {
            resolve();
            return;
          }
          setTimeout(tick, Math.min(poll, deadline - Date.now()));
        };
        tick();
      });

    let aborted = false;
    const start = Date.now();
    const pending = abortableSleep(10000, () => aborted).then(() => Date.now() - start);
    setTimeout(() => {
      aborted = true; // 100ms 後に停止押下相当
    }, 100);
    const elapsed = await pending;
    return { elapsed };
  });

  expect(result.elapsed).toBeGreaterThanOrEqual(100); // 中断フラグが立つまでは待つ
  expect(result.elapsed).toBeLessThan(3000); // 受け入れ条件: 停止後 3 秒以内に抜ける
});
