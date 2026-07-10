// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行に使う DOM 操作群。
// 旧 `content.js` の振る舞いを 1:1 で保持しつつ純関数化する。
// Suno の DOM は変わりうるため、セレクタはこの 1 箇所に集約する（壊れたら README 参照で更新）。

import { isVisible } from "./visibility";

// Suno の DOM セレクタ SSOT。#807 で判明したとおり placeholder は UI ロケールで変わるため、
// Lyrics は言語非依存の data-testid で識別する（Style は「Lyrics でない可視 textarea」）。
const SELECTORS = {
  textareas: "textarea",
  lyrics: '[data-testid="lyrics-textarea"]',
  // 2026-07 の Suno UI 改装で Lyrics 欄が textarea から Lexical エディタ
  // (div.lyrics-editor-content[contenteditable][data-lexical-editor]) へ変わった。
  // 旧 UI との併存を考慮し testid textarea を最優先、この selector は fallback。
  // data-lexical-editor は通常の contenteditable と区別する構造根拠。
  // contenteditable="" も有効値（属性値なしの boolean 形式）なので両方拾う。
  lyricsLexical:
    'div.lyrics-editor-content[data-lexical-editor][contenteditable="true"], div.lyrics-editor-content[data-lexical-editor][contenteditable=""]',
  // Style 欄の wrapper（新 UI 実 DOM で確認）。Lyrics が textarea でなくなり
  // 「Lyrics 以外の可視 textarea」述語だけでは Style の特定根拠が弱くなったため一次識別にする。
  stylesWrapper: '[data-testid="create-form-styles-wrapper"]',
  // Song Title 欄は testid/aria/label を持たず placeholder のみ安定 (#844 実 DOM 検証)。
  // 英語 UI は "Song Title (Optional)"、日本語 UI は "曲名(任意)"（2026-07 実 DOM）で出る。
  title: 'input[placeholder*="Song Title" i], input[placeholder*="曲名"]',
  // Custom Mode > More Options の 3 フィールド (#900、chrome-devtools-mcp で実機確定済み)。
  //   - Exclude styles: native text input/textarea (placeholder / aria-label の表記ゆれを許容)
  //   - Weirdness / Style Influence: radix slider ([role="slider"] + aria-label で区別)
  // data-testid は Suno UI で Lyrics 以外に存在しないため placeholder / aria-label を SSOT にする。
  excludeStyles:
    'input[placeholder*="Exclude" i], textarea[placeholder*="Exclude" i], input[aria-label*="Exclude" i], textarea[aria-label*="Exclude" i], input[placeholder*="除外"], textarea[placeholder*="除外"], input[aria-label*="除外"], textarea[aria-label*="除外"]',
  // 2026-07 の Suno 新 Create UI で slider がリネームされた（Weirdness → Bizarreness /
  // Style Influence → Style influence〈小文字 i〉、#1720）。完全一致だと表記ゆれのたびに run が
  // 中断するため、旧新両ラベルにマッチする case-insensitive substring match（tolerant match）にする。
  weirdness:
    '[role="slider"][aria-label*="weirdness" i], [role="slider"][aria-label*="bizarre" i]',
  styleInfluence: '[role="slider"][aria-label*="influence" i]',
  // Voice section の Male / Female ボタン (chrome-devtools-mcp 実機検証で確認)。
  // aria-label / data-testid を持たないため、`data-selected` 属性 (Suno が排他トグル用に意図して
  // 付けた属性) で候補を全 query → textContent 完全一致で Male/Female を絞り込む方式を採用。
  // Emotion class hash や親 div の role/class には依存しない。
  vocalGenderButtons: 'button[data-selected][type="button"]',
  generateLabel: /^(create|generate|生成|作成(?:する)?)$/i,
  recaptcha:
    'iframe[src*="recaptcha"], iframe[title*="recaptcha" i], iframe[src*="hcaptcha"]',
} as const;

/** radix slider 注入の step ごとの読み戻し検証の poll 間隔 (ms)。 */
const SLIDER_READBACK_POLL_MS = 100;
/** step ごとの読み戻し検証の最大 poll 回数。これを超えても不変なら fail-loud で throw。 */
const SLIDER_READBACK_MAX_POLLS = 5;
/** slider が target に到達するまでの最大 step 数。Suno slider は 0-100 整数なので余裕を持たせた上限。 */
const SLIDER_MAX_STEPS = 150;

/**
 * clip カードの in-flight マーカー（#866、実機検証で確定）。Suno が `data-testid="clip-row"` と
 * `svg.animate-spin` を撤去したため、音源が揃わない限り押せない Remix btn の `disabled` を軸にする。
 * UI 装飾（spinner/testid）と違い「音源未完成なら Remix 不可」という Suno のドメインルール由来で変更されにくい。
 */
export const REMIX_BTN_SELECTOR = 'button[aria-label="Remix clip"]';
/** clip card root を構造的に解決するための同伴ボタン（#866）。Remix btn と合わせ 3 種が各 1 つ揃う祖先が card。 */
const SELECT_CLIP_BTN_SELECTOR = 'button[aria-label="Select clip"]';
const DESELECT_CLIP_BTN_SELECTOR = 'button[aria-label="Deselect clip"]';
const EDIT_TITLE_BTN_SELECTOR = 'button[aria-label="Edit title"]';
export type SunoViewMode = "list" | "waveform" | "grid" | "unknown";
const SUNO_VIEW_LABELS: Record<
  Exclude<SunoViewMode, "unknown">,
  readonly string[]
> = {
  list: ["list"],
  waveform: ["waveform"],
  grid: ["grid"],
};
/**
 * queue 上限エラー toast の安定識別子（#847、実 DOM 検証）。testid/aria-label を持たないため
 * `[role="dialog"]` + 英語見出しテキストの substring match で識別する（多言語耐性）。
 */
export const QUEUE_LIMIT_ERROR_SELECTOR = '[role="dialog"]';
/** queue 上限エラー toast の英語見出し（case-insensitive substring match。日本語並列テキストには依存しない）。 */
const QUEUE_LIMIT_ERROR_TEXT = "generation in progress";

/** 1 曲の生成完了待ち上限 (ms)。 */
export const GENERATE_TIMEOUT_MS = 180000;
/**
 * captcha challenge の解消待ち上限 (ms)。Suno の hCaptcha は Generate click に反応して起動するが、
 * 多くは passive 検証で数秒以内に自動 verify されて閉じるため、即 fail-loud せず解消を待つ。
 * 本当に人間の解決が必要な challenge が残った場合のみ、この上限で fail-loud に倒す。
 */
export const CAPTCHA_WAIT_TIMEOUT_MS = 600000;
/** 生成完了 poll 間隔 (ms)。短くすると停止反応性と Generate ボタン再 enable 検知が早まる。 */
export const POLL_INTERVAL_MS = 500;
/** 注入後・クリック後の安定化待ち (ms)。 */
export const SETTLE_MS = 1500;

/**
 * run 全体を止めるべき致命的エラー (#948)。entry 単位のリトライ/スキップ（lib/entry-retry.ts）の
 * 対象外で、catch されず ERROR phase へ直行する。該当するのは「次の entry でも必ず再発する」失敗:
 *   - DOM セレクタ不在（Suno UI 改装 / Custom Mode 画面でない）
 *   - captcha challenge の手動解決待ち timeout（人間の介入が必要）
 *   - queue の stall / timeout（Suno 側の系統的な停滞）
 * 一時的・entry 固有の失敗（生成完了待ち timeout / inject 未受理）は通常の Error のまま残す。
 */
export class FatalRunError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FatalRunError";
  }
}

export interface ResolvedFields {
  style: HTMLTextAreaElement;
  /** 旧 UI は textarea、新 UI (2026-07) は Lexical contenteditable div。注入は setLyricsValue が分岐する。 */
  lyrics: HTMLTextAreaElement | HTMLElement | null;
  // Song Title 欄 (#844)。不在は throw せず undefined（fail-soft: style/lyrics の fail-loud とは非対称）。
  title?: HTMLInputElement;
}

export interface WaitForGenerationOptions {
  /** 中断フラグ。true を返した時点で待機を打ち切り resolve する。 */
  isAborted: () => boolean;
  timeoutMs: number;
  pollIntervalMs: number;
  settleMs: number;
  /** captcha 解消待ちの上限 (ms)。省略時は CAPTCHA_WAIT_TIMEOUT_MS。 */
  captchaWaitTimeoutMs?: number;
  /** captcha 解消待ちの開始 (true) / 終了 (false) 通知。popup の phase 表示切り替えに使う。 */
  onCaptchaWait?: (waiting: boolean) => void;
}

/** 指定 ms 待機する。注入フローと生成完了待ちの共通 timing util。 */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** abortableSleep の中断検知 poll 間隔 (ms)。停止押下から resolve までの粒度（受け入れ条件: 3 秒以内停止に十分小さい）。 */
const ABORTABLE_SLEEP_POLL_MS = 250;

/**
 * 中断可能な sleep (#847)。`ms` 経過 または `isAborted()` が true になった時点（内部 poll で検知）の
 * 早い方で resolve する。`sleep` と同じく throw / reject しない。連続実行フローの固定待機を本関数に
 * 置き換えることで、長い待機の途中でも停止押下に素早く反応できる。
 */
export function abortableSleep(
  ms: number,
  isAborted: () => boolean,
): Promise<void> {
  return new Promise((resolve) => {
    const deadline = Date.now() + ms;
    const tick = (): void => {
      if (isAborted() || Date.now() >= deadline) {
        resolve();
        return;
      }
      // 残り時間と poll 間隔の短い方を待つ（最終 tick が deadline をオーバーランしないように）。
      setTimeout(
        tick,
        Math.min(ABORTABLE_SLEEP_POLL_MS, deadline - Date.now()),
      );
    };
    tick();
  });
}

/** React 互換のネイティブ値セット + input/change イベント発火。 */
export function setNativeValue(
  el: HTMLTextAreaElement | HTMLInputElement,
  value: string,
): void {
  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (!setter) {
    throw new Error("native value setter を取得できませんでした。");
  }
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

/**
 * Lexical エディタの selection 同期待ち (ms)。execCommand("selectAll") の選択は Lexical が
 * selectionchange 経由で内部 state に取り込むため反映が非同期になる。paste dispatch 前に
 * 待たないと全選択が内部 state に乗らず「置換」でなく「先頭挿入」に化ける（実機検証）。
 * paste 後の待ちは Lexical の DOM 反映（reconcile）完了を待つ安定化マージン。
 */
const LEXICAL_SELECTION_SYNC_MS = 200;

/**
 * Lexical は改行ごとに直下の p 要素へ分割するため、textContent では段落境界が消える。
 * p 要素がある場合は改行で再結合し、投入元の plain text と同じ表現へ戻して検証する。
 */
function readLexicalText(el: HTMLElement): string {
  const paragraphs = Array.from(el.children).filter(
    (child): child is HTMLElement =>
      child instanceof HTMLElement && child.tagName === "P",
  );
  return paragraphs.length > 0
    ? paragraphs.map((paragraph) => paragraph.textContent ?? "").join("\n")
    : (el.textContent ?? "");
}

/**
 * Lyrics 欄への値注入。旧 UI の textarea / input は setNativeValue へ委譲し、
 * 新 UI (2026-07) の Lexical contenteditable div は selectAll 後、非空 lyrics を paste 合成イベントで
 * 全置換し、空 lyrics は delete command でクリアする。
 *
 * Lexical は value setter を持たず、innerText 直接代入は内部 EditorState と乖離して
 * 次の再レンダーで巻き戻る。Lexical 自身が購読する paste イベント（DataTransfer の
 * text/plain）に載せるのが React 互換で最も壊れにくい経路（実ページで動作検証済み）。
 * 空の text/plain paste は Lexical 側で no-op になる可能性があるため、空 lyrics は全選択後に
 * delete command でクリアする。
 * 同期実行では selection が Lexical に同期されず置換に失敗するため async 必須。
 */
export async function setLyricsValue(
  el: HTMLTextAreaElement | HTMLElement,
  value: string,
): Promise<void> {
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {
    setNativeValue(el, value);
    return;
  }
  el.focus();
  const selected = document.execCommand("selectAll", false);
  if (!selected) {
    throw new FatalRunError(
      "Lyrics 欄の全選択に失敗しました。Suno UI の Lexical editor 状態を確認してください。",
    );
  }
  await sleep(LEXICAL_SELECTION_SYNC_MS);
  if (value === "") {
    const cleared = document.execCommand("delete", false);
    if (!cleared) {
      throw new FatalRunError(
        "Lyrics 欄のクリアに失敗しました。Suno UI の Lexical editor 状態を確認してください。",
      );
    }
    await sleep(LEXICAL_SELECTION_SYNC_MS);
    if (readLexicalText(el) !== "") {
      el.dispatchEvent(
        new InputEvent("beforeinput", {
          bubbles: true,
          cancelable: true,
          composed: true,
          data: null,
          inputType: "deleteContentBackward",
        }),
      );
      await sleep(LEXICAL_SELECTION_SYNC_MS);
      if (readLexicalText(el) !== "") {
        throw new FatalRunError(
          "Lyrics 欄のクリア反映に失敗しました。Generate へ進まず停止します。",
        );
      }
    }
    return;
  }
  const data = new DataTransfer();
  data.setData("text/plain", value);
  el.dispatchEvent(
    new ClipboardEvent("paste", {
      clipboardData: data,
      bubbles: true,
      cancelable: true,
    }),
  );
  await sleep(LEXICAL_SELECTION_SYNC_MS);
  if (readLexicalText(el) !== value) {
    throw new FatalRunError(
      "Lyrics 欄への paste 反映に失敗しました。Generate へ進まず停止します。",
    );
  }
}

/**
 * radix Slider に target 値を注入する（#900, #979 で step 化）。
 *   1. slider.focus()
 *   2. aria-valuenow を読み、target との差分方向の keydown を **1 step ずつ** dispatch
 *   3. 各 step 後に aria-valuenow の変化を poll（SLIDER_READBACK_POLL_MS × SLIDER_READBACK_MAX_POLLS）。
 *      変化を確認してから次の step へ進む。不変のまま poll が尽きたら throw（fail-loud）
 *   4. aria-valuenow === target で resolve
 *
 * 全 diff 分を同期ループで一括 dispatch すると React の自動バッチングで stale 値に収束し
 * net 1 step しか動かない（#979 実機検証）。isTrusted=false の合成イベント自体は弾かれて
 * おらず、1 step ごとに re-render の反映を待てば target まで完走する。
 *
 * KeyboardEvent は `bubbles: true, composed: true` で dispatch する。radix Slider root は
 * keydown を addEventListener でバインドし bubbling 経由で受けるため root に到達する。
 */
export async function setSliderValue(
  slider: HTMLElement,
  target: number,
): Promise<void> {
  slider.focus();
  const read = (): number => Number(slider.getAttribute("aria-valuenow"));
  const fail = (): never => {
    throw new Error(
      `slider 値の注入に失敗しました（target=${target}, actual=${slider.getAttribute("aria-valuenow")}, ` +
        `aria-label=${slider.getAttribute("aria-label") ?? "?"}）。` +
        "keydown 後も aria-valuenow が変化しませんでした。Suno の UI 変更の可能性があります。",
    );
  };
  for (let step = 0; step < SLIDER_MAX_STEPS; step++) {
    const current = read();
    if (current === target) {
      return;
    }
    const key = target > current ? "ArrowRight" : "ArrowLeft";
    slider.dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, composed: true }),
    );
    // 同期反映ならそのまま次 step へ。非同期 re-render は poll で変化を待つ。
    let changed = read() !== current;
    for (
      let attempt = 0;
      !changed && attempt < SLIDER_READBACK_MAX_POLLS;
      attempt++
    ) {
      await sleep(SLIDER_READBACK_POLL_MS);
      changed = read() !== current;
    }
    if (!changed) {
      fail();
    }
  }
  if (read() !== target) {
    fail();
  }
}

/** More Options の advanced フィールド解決結果（#900, vocal gender 追加）。不在は null（fail-soft）。 */
export interface ResolvedAdvancedFields {
  excludeStyles: HTMLInputElement | HTMLTextAreaElement | null;
  weirdness: HTMLElement | null;
  styleInfluence: HTMLElement | null;
  /** Voice section の Male / Female ボタンペア。将来 neutral 等が追加されても nested で拡張しやすい形にしておく。 */
  vocalGender: {
    male: HTMLButtonElement | null;
    female: HTMLButtonElement | null;
  };
}

/** injectAdvancedFields が読む entry の advanced 値（PromptEntry の部分集合）。 */
export interface AdvancedFieldValues {
  style_influence?: number;
  weirdness?: number;
  exclude_styles?: string;
  vocal_gender?: "male" | "female" | "neutral" | "auto";
}

/**
 * 候補から「visible 優先、なければ最初の要素」を返す（#900 改）。
 * Suno は More Options collapsed 時に祖先を display:none で隠す。input には setNativeValue
 * で値を入れれば React props まで更新されること、slider は visible でも合成イベントが効かないこと
 * を実機検証で確認済み。strict visible 必須を緩めて collapsed 時も DOM 上の要素を掴むことで、
 * input は値が入り（解決）、slider は注入時に fail-soft で skip（injectAdvancedFields 側）になる。
 */
function pickPreferVisible<T extends HTMLElement>(els: T[]): T | null {
  return els.find(isVisible) ?? els[0] ?? null;
}

/**
 * Custom Mode > More Options の 3 フィールドを解決する（#900）。
 * visible 優先、なければ DOM 上の最初の要素を返す（collapsed 時の null 化を回避）。
 * 3 要素すべて不在でも throw しない（fail-soft）。throw / skip の非対称契約は呼び出し側
 * (injectAdvancedFields) が entry の値有無と突き合わせて判定する。
 */
export function resolveAdvancedFields(): ResolvedAdvancedFields {
  const excludeStyles = pickPreferVisible(
    Array.from(
      document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(
        SELECTORS.excludeStyles,
      ),
    ),
  );
  const weirdness = pickPreferVisible(
    Array.from(document.querySelectorAll<HTMLElement>(SELECTORS.weirdness)),
  );
  const styleInfluence = pickPreferVisible(
    Array.from(
      document.querySelectorAll<HTMLElement>(SELECTORS.styleInfluence),
    ),
  );
  return {
    excludeStyles,
    weirdness,
    styleInfluence,
    vocalGender: resolveVocalGenderButtons(),
  };
}

/**
 * Voice section の Male / Female ボタンを解決する。
 * data-selected 属性で候補を全 query → textContent 完全一致 ("Male" / "Female") で絞り込み。
 * pickPreferVisible で visible 優先（collapsed 時の fallback として hidden も拾う）。
 * 不在は null（fail-soft）。判定は case-sensitive（"male" lowercase 等は拾わない）。
 */
function resolveVocalGenderButtons(): {
  male: HTMLButtonElement | null;
  female: HTMLButtonElement | null;
} {
  const candidates = Array.from(
    document.querySelectorAll<HTMLButtonElement>(SELECTORS.vocalGenderButtons),
  );
  const findByLabel = (label: "Male" | "Female"): HTMLButtonElement | null =>
    pickPreferVisible(
      candidates.filter((b) => b.textContent?.trim() === label),
    );
  return { male: findByLabel("Male"), female: findByLabel("Female") };
}

/**
 * entry の advanced 値を解決済み field へ注入する（#900）。
 * 注入順序は Exclude styles (text, 高速) → Weirdness → Style Influence。
 *
 * 非対称契約:
 *   - entry に値有 (`!== undefined`) + 対応 selector が null → input / vocal_gender は throw（fail-loud、UI 改装検知）。
 *     slider 2 つは warn + skip（#1720。slider 値は UI で手動設定でき Create を跨いで永続するため、
 *     Suno のリネームによる未検出は run 中断に値しない。skip は onSliderSkip で観測可能にする）
 *   - entry に値無 (`=== undefined`)                        → skip（fail-soft、後方互換）
 *   - entry に値有 + selector 有 + input                    → setNativeValue で注入（collapsed でも React 反映を実機確認済み）
 *   - entry に値有 + selector 有 + slider                   → 注入試行し失敗時は warn + skip
 *   - vocal_gender = "male" / "female"                     → 対応ボタンが既に data-selected=true なら skip、false なら click（冪等）
 *   - vocal_gender = "neutral" / "auto"                    → click しない（既選択を解除しない、"Auto = Suno に任せる"解釈）
 *
 * slider fail-soft 化の根拠（実機検証）:
 *   Suno の Weirdness / Style Influence slider は emotion 自作で onKeyDown 内に isTrusted チェックが
 *   ある。合成 KeyboardEvent / MouseEvent / PointerEvent はすべて弾かれ、現状の dispatchEvent 方式では
 *   原理的に値を変えられない。bot 対策で組み込まれていると見られる。throw で連続生成を止めるとユーザー
 *   体験が大きく劣化するため、本 PR では注入失敗を warn + skip で吸収する。trusted event 経由の真の
 *   解決は別 issue で chrome.debugger API ベースの設計を予定（manifest permission 拡張が必要）。
 *
 * 値の有無は `!== undefined` で判定する。0 や "" の falsy 値を truthy 判定で脱落させない。
 *
 * slider 注入経路（#973）: options.bridgeSetSlider があれば MAIN world bridge 経由
 * （React onKeyDown 直接呼び出し = isTrusted チェック通過）を先に試し、失敗時に従来の
 * 合成 dispatchEvent（setSliderValue）へ縮退する。どちらも失敗なら warn + skip（従来どおり）。
 */
export interface AdvancedInjectOptions {
  /** MAIN world bridge 経由の slider 注入。成功で true。省略時は合成イベント経路のみ。 */
  bridgeSetSlider?: (ariaLabel: string, target: number) => Promise<boolean>;
  /** slider を warn + skip したときの通知（#1720）。呼び出し側が overlay / popup へ
   * skip を観測可能にするために使う（サイレント skip の禁止）。省略時は console.warn のみ。 */
  onSliderSkip?: (sliderName: "Weirdness" | "Style Influence") => void;
}

/** bridge 優先 → 合成 dispatchEvent 縮退の順で slider に target 値を注入する（#973）。 */
async function injectSliderValue(
  slider: HTMLElement,
  target: number,
  bridgeSetSlider?: (ariaLabel: string, target: number) => Promise<boolean>,
): Promise<void> {
  if (bridgeSetSlider) {
    const label = slider.getAttribute("aria-label");
    if (label) {
      try {
        if (await bridgeSetSlider(label, target)) {
          return;
        }
      } catch {
        // bridge 経路の失敗は合成イベント経路へ縮退する（fail-soft）。
      }
    }
  }
  await setSliderValue(slider, target);
}

export async function injectAdvancedFields(
  entry: AdvancedFieldValues,
  fields: ResolvedAdvancedFields,
  options: AdvancedInjectOptions = {},
): Promise<void> {
  if (entry.exclude_styles !== undefined) {
    if (!fields.excludeStyles) {
      throw new FatalRunError(
        "Exclude styles 欄が見つかりません。Suno の「書く」モードでその他のオプションを開いてから再実行してください。",
      );
    }
    setNativeValue(fields.excludeStyles, entry.exclude_styles);
  }
  if (entry.vocal_gender === "male" || entry.vocal_gender === "female") {
    const target =
      entry.vocal_gender === "male"
        ? fields.vocalGender.male
        : fields.vocalGender.female;
    if (!target) {
      throw new FatalRunError(
        `Vocal gender button (${entry.vocal_gender}) が見つかりません。Suno の UI 変更の可能性があります。`,
      );
    }
    if (target.getAttribute("data-selected") !== "true") {
      target.click();
    }
  }
  if (entry.weirdness !== undefined) {
    // slider 未検出は throw せず warn + skip（#1720）。値は UI で手動設定でき Create を跨いで
    // 永続するため、Suno のリネーム / UI 改装で run 全体を中断しない。
    if (!fields.weirdness) {
      console.warn(
        "[suno-helper] Weirdness slider が見つかりません（Suno の UI 変更の可能性）。注入を skip して続行します。",
      );
      options.onSliderSkip?.("Weirdness");
    } else {
      try {
        await injectSliderValue(
          fields.weirdness,
          entry.weirdness,
          options.bridgeSetSlider,
        );
      } catch (e) {
        console.warn("[suno-helper] Weirdness slider 注入を skip:", e);
        options.onSliderSkip?.("Weirdness");
      }
    }
  }
  if (entry.style_influence !== undefined) {
    if (!fields.styleInfluence) {
      console.warn(
        "[suno-helper] Style Influence slider が見つかりません（Suno の UI 変更の可能性）。注入を skip して続行します。",
      );
      options.onSliderSkip?.("Style Influence");
    } else {
      try {
        await injectSliderValue(
          fields.styleInfluence,
          entry.style_influence,
          options.bridgeSetSlider,
        );
      } catch (e) {
        console.warn("[suno-helper] Style Influence slider 注入を skip:", e);
        options.onSliderSkip?.("Style Influence");
      }
    }
  }
}

/**
 * challenge 系 iframe か（anchor / checkbox / badge 系 widget は除外）。
 * hCaptcha challenge は src に `#frame=challenge`、reCAPTCHA challenge は `/bframe` を含む。
 * anchor / checkbox / badge 系 widget は常時 title を持つため、title 判定を challenge 系に限定する (#924)。
 */
function isChallengeFrame(src: string): boolean {
  return src.includes("frame=challenge") || src.includes("/bframe");
}

/**
 * active な recaptcha / hcaptcha challenge iframe を検知する（#810, #875, #924）。
 * Suno は hCaptcha challenge を非表示プリロード iframe として常駐させるため、
 * querySelector の hit だけでは常に true になってしまう。
 *
 * #875 で判明した中間状態: silent drop タイミングで iframe の `title` が `""` →
 * `"hCaptchaチャレンジ"` に変化するが `visibility:hidden` は維持される。従来の strict
 * `isVisible()` だけでは visibility:hidden で false となり silent drop に流れていた。
 * そこで bbox を持つ（プリロードでない）**challenge 系** iframe の `title` が non-empty なら、
 * visibility に関わらず active challenge とみなす。
 *
 * #924 で判明した誤検知: title 非空ヒューリスティックを全 iframe に適用すると、
 * anchor / checkbox / badge 系の常駐 widget iframe（reCAPTCHA anchor は title="reCAPTCHA"、
 * hCaptcha checkbox widget も常時 title あり）まで誤検知してしまう。
 * title 非空ヒューリスティックは challenge 系 iframe（`frame=challenge` / `/bframe`）に限定し、
 * それ以外の iframe は従来通り strict isVisible() のみで判定する。
 */
export function detectRecaptcha(): boolean {
  const iframes = document.querySelectorAll<HTMLIFrameElement>(
    SELECTORS.recaptcha,
  );
  return Array.from(iframes).some((f) => {
    // bbox 0 のプリロード iframe は title を持っていても active ではない（title 判定より優先）。
    const rect = f.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
      return false;
    }
    // 検証完了後の challenge iframe は title と bbox を保持したまま画面外 (y:-9999) に駐機する。
    // viewport 上端より完全に上へ退避した iframe は active ではない（title 判定より優先）。
    // 実機観測: 駐機 wrapper は visibility:hidden + opacity:0 + z-index:-2147483648。
    const parkedOffscreen = rect.bottom <= 0;
    // challenge 系 iframe かつ title 非空 = challenge が起動した中間状態。
    // visibility:hidden を許容して捕捉する (#875)。
    // anchor / checkbox / badge 系 widget は常時 title を持つため challenge 系に限定 (#924)。
    const active =
      (isChallengeFrame(f.src) &&
        f.title.trim().length > 0 &&
        !parkedOffscreen) ||
      isVisible(f);
    if (active) {
      console.debug("[suno-helper] captcha challenge iframe detected", {
        src: f.src,
        title: f.title,
        bbox: { width: rect.width, height: rect.height },
        visibility: getComputedStyle(f).visibility,
      });
    }
    return active;
  });
}

/**
 * queue 上限エラー toast が表示中かを検知する（#847）。
 * 可視な `[role="dialog"]` のうち英語見出し "generation in progress" を case-insensitive
 * substring match で含むものがあれば true。detectRecaptcha (#810) と同じ strict isVisible で
 * 非表示の toast 残骸を弾く。Create→clip card DOM 反映ラグで Suno が投入を reject した時に出る toast を
 * 検知し、空きスロットがあっても投入を止めるために使う。
 */
export function isQueueLimitErrorVisible(): boolean {
  const dialogs = document.querySelectorAll<HTMLElement>(
    QUEUE_LIMIT_ERROR_SELECTOR,
  );
  return Array.from(dialogs).some(
    (el) =>
      isVisible(el) &&
      (el.textContent ?? "").toLowerCase().includes(QUEUE_LIMIT_ERROR_TEXT),
  );
}

/**
 * Style / Lyrics の入力欄を解決する（#807、2026-07 Lexical 改装対応）。
 *   - Lyrics: `data-testid="lyrics-textarea"` を最優先で識別（UI 言語非依存、旧 UI）。無ければ
 *             Lexical contenteditable（`div.lyrics-editor-content[data-lexical-editor]`、新 UI）を
 *             bbox 幅非ゼロで拾う。
 *             どちらも無ければ null。Lexical 側の可視判定を strict isVisible でなく幅判定にするのは
 *             実ページで動作検証した条件をそのまま保持するため（wrapper の opacity 等の transition
 *             で誤除外しない安全側）。
 *   - Style:  styles-wrapper (`create-form-styles-wrapper`) 内の可視 textarea を一次識別とする。
 *             Lyrics が textarea でなくなった新 UI では「Lyrics 以外」述語だけだと無関係な
 *             textarea を誤って掴みうるため、wrapper の構造根拠を優先する。wrapper 不在の
 *             旧 UI は従来の「Lyrics 以外の可視 textarea」へ fallback（この述語が
 *             Style==Lyrics の silent 上書きを構造的に禁ずる）。
 *   - Style が解決できない場合は throw（silent スキップを禁ずる）。
 *   - Title:  placeholder substring match の strict visible input（#844）。不在は undefined（fail-soft）。
 */
export function resolveFields(): ResolvedFields {
  const areas = Array.from(
    document.querySelectorAll<HTMLTextAreaElement>(SELECTORS.textareas),
  ).filter(isVisible);
  if (areas.length === 0) {
    throw new FatalRunError(
      "textarea が見つかりません。Suno の Custom Mode 画面を開いてください。",
    );
  }

  const lyrics: HTMLTextAreaElement | HTMLElement | null =
    areas.find((el) => el.matches(SELECTORS.lyrics)) ??
    Array.from(
      document.querySelectorAll<HTMLElement>(SELECTORS.lyricsLexical),
    ).find((el) => el.getBoundingClientRect().width > 0) ??
    null;
  // Style は wrapper 構造を一次識別、無ければ「Lyrics でない可視 textarea」。
  const style =
    areas.find((el) => el.closest(SELECTORS.stylesWrapper) !== null) ??
    areas.find((el) => el !== lyrics);
  if (!style) {
    throw new FatalRunError(
      "Style 欄が見つかりません。Lyrics 以外の可視 textarea を検出できませんでした。",
    );
  }

  // Title は style/lyrics と別クエリ（<input>）。不在でも throw しない fail-soft で undefined を返す。
  const title = Array.from(
    document.querySelectorAll<HTMLInputElement>(SELECTORS.title),
  ).find(isVisible);

  return { style, lyrics, title };
}

/** Generate ボタンを解決する。可視ボタンに該当ラベルが無ければ throw。 */
export function resolveGenerateButton(): HTMLButtonElement {
  const buttons = Array.from(
    document.querySelectorAll<HTMLButtonElement>("button"),
  ).filter(isVisible);
  const btn = buttons.find((el) =>
    SELECTORS.generateLabel.test((el.textContent || "").trim()),
  );
  if (!btn) {
    throw new FatalRunError(
      "生成ボタン（Create / Generate / 作成）が見つかりません。Suno の UI 変更または UI 言語ラベル変更の可能性があります。",
    );
  }
  return btn;
}

export interface WaitForCaptchaClearOptions {
  /** 中断フラグ。true を返した時点で待機を打ち切り resolve する（throw しない）。 */
  isAborted: () => boolean;
  pollIntervalMs: number;
  timeoutMs: number;
  /** captcha を検知して待機に入るとき 1 回だけ呼ばれる。popup の phase 表示切り替えに使う。 */
  onWaitStart?: () => void;
}

/**
 * active な captcha challenge が解消されるまで待つ。
 * Suno の hCaptcha は Generate click に反応して起動するが、多くは passive 検証で数秒以内に
 * 自動 verify されて閉じる（console: `captcha required` → `captcha verified`）。従来の即 throw だと
 * 人間が解くものが無いのに entry ごとに fail-loud 停止して実用に耐えないため、解消を待って続行する。
 *   - captcha 不在なら即 resolve（onWaitStart も呼ばない）
 *   - 解消（自動 verify or 手動解決）で resolve
 *   - timeoutMs 超過で throw（本当に人間の解決が必要なまま放置されたケースのみ fail-loud）
 *   - 中断 (isAborted) で即 return
 */
export async function waitForCaptchaClear(
  options: WaitForCaptchaClearOptions,
): Promise<void> {
  if (!detectRecaptcha()) {
    return;
  }
  options.onWaitStart?.();
  const deadline = Date.now() + options.timeoutMs;
  while (Date.now() < deadline) {
    if (options.isAborted()) {
      return;
    }
    if (!detectRecaptcha()) {
      return;
    }
    await sleep(options.pollIntervalMs);
  }
  throw new FatalRunError(
    `captcha challenge が ${Math.round(options.timeoutMs / 60000)} 分以内に解消されませんでした。画面の challenge を手動で解決してから再開してください。`,
  );
}

/**
 * クリック後、ボタンが一旦 disabled になり再度 enabled に戻るまで（= 生成完了）待つ。
 *   - enabled 復帰で resolve
 *   - captcha 検知で waitForCaptchaClear へ移行し、解消後に待機を続行（待機時間は deadline を消費しない）
 *   - captcha が captchaWaitTimeoutMs 以内に解消されなければ throw
 *   - deadline 超過で timeout throw
 *   - 中断 (isAborted) で即 return
 */
export async function waitForGeneration(
  button: HTMLButtonElement,
  options: WaitForGenerationOptions,
): Promise<void> {
  let deadline = Date.now() + options.timeoutMs;
  // disabled に変わるのを少し待つ（生成開始の検知）
  await sleep(options.settleMs);
  while (Date.now() < deadline) {
    if (options.isAborted()) {
      return;
    }
    if (detectRecaptcha()) {
      // captcha 解消待ちは生成完了待ちとは別系統の時間。deadline を待機分だけ延長する。
      const waitStart = Date.now();
      await waitForCaptchaClear({
        isAborted: options.isAborted,
        pollIntervalMs: options.pollIntervalMs,
        timeoutMs: options.captchaWaitTimeoutMs ?? CAPTCHA_WAIT_TIMEOUT_MS,
        onWaitStart: () => options.onCaptchaWait?.(true),
      });
      options.onCaptchaWait?.(false);
      deadline += Date.now() - waitStart;
      continue;
    }
    if (!button.disabled && button.getAttribute("aria-disabled") !== "true") {
      return;
    }
    await sleep(options.pollIntervalMs);
  }
  throw new Error("生成完了の検知がタイムアウトしました。");
}

export interface WaitForQueueSlotOptions {
  /** 中断フラグ。true を返した時点で待機を打ち切り resolve する（throw しない）。 */
  isAborted: () => boolean;
  pollIntervalMs: number;
  timeoutMs: number;
  /** queue 上限エラー toast 消失後に投入再開まで待つ安全マージン (ms、#847)。 */
  queueErrorWaitMs: number;
  /** in-flight 数の取得関数 (#948)。bridge の status ベースカウントを注入する。
   * 省略時は従来の DOM プロキシ getInFlightClipCount（後方互換 fallback）。 */
  getCount?: () => number;
  /** in-flight 集合が最後に変化した時刻 (ms) の取得関数 (#948)。注入すると stall ベース判定に切り替わる:
   * 固定 deadline を廃し、「待機開始 or 最終変化からの経過が stallTimeoutMs を超えたときのみ throw」。
   * 正確なカウントの下では上限での長い待ちは正常状態のため、固定 deadline は誤停止になる。 */
  getLastChangeAt?: () => number;
  /** stall 判定の閾値 (ms)。getLastChangeAt 注入時のみ有効。省略時は INFLIGHT_STALL_TIMEOUT_MS 相当を
   * 呼び出し側が渡す想定（shared/dom は定数 SSOT の constants.ts に依存しない）。 */
  stallTimeoutMs?: number;
}

export function detectSunoViewMode(): SunoViewMode {
  const selectedModes = collectViewModesFromElements(
    document.querySelectorAll<HTMLElement>(
      '[aria-selected="true"], [aria-current="true"], [data-state="checked"]',
    ),
  );
  const selected = singleModeOrUnknown(selectedModes);
  if (selected !== "unknown") {
    return selected;
  }
  if (selectedModes.size > 1) {
    return "unknown";
  }

  // Suno 2026-06: ビューモードボタンが data-context-menu-trigger 属性のみのプレーンボタンに変更。
  // 現在選択中のビューモードボタンだけがこの属性を持ち、テキストがモード名と一致する。
  const contextMenuModes = collectViewModesFromElements(
    document.querySelectorAll<HTMLElement>("button[data-context-menu-trigger]"),
  );
  const contextMenu = singleModeOrUnknown(contextMenuModes);
  if (contextMenu !== "unknown") {
    return contextMenu;
  }
  if (contextMenuModes.size > 1) {
    return "unknown";
  }

  const triggerModes = collectViewModesFromElements(
    document.querySelectorAll<HTMLElement>(
      'button[aria-haspopup], button[aria-expanded], [role="button"][aria-haspopup], [role="button"][aria-expanded]',
    ),
  );
  const trigger = singleModeOrUnknown(triggerModes);
  if (trigger !== "unknown") {
    return trigger;
  }
  if (triggerModes.size > 1) {
    return "unknown";
  }

  // Suno 2025-06 以降: ビューモードボタンが ARIA 属性を持たないプレーンボタンに変更された。
  // visible な button 要素のテキストから view mode ラベルを探す fallback。
  const plainBtnModes = collectViewModesFromElements(
    document.querySelectorAll<HTMLElement>("button"),
  );
  const plain = singleModeOrUnknown(plainBtnModes);
  if (plain !== "unknown") {
    return plain;
  }

  return "unknown";
}

function normalizeViewModeLabel(text: string): SunoViewMode {
  const tokens = text
    .trim()
    .toLowerCase()
    .replace(/[^a-z]+/g, " ")
    .split(/\s+/)
    .filter((token) => token.length > 0);
  const matchedModes = new Set<Exclude<SunoViewMode, "unknown">>();
  for (const [mode, expectedLabels] of Object.entries(SUNO_VIEW_LABELS)) {
    if (expectedLabels.some((label) => tokens.includes(label))) {
      matchedModes.add(mode as Exclude<SunoViewMode, "unknown">);
    }
  }
  if (matchedModes.size === 1) {
    return Array.from(matchedModes)[0];
  }
  return "unknown";
}

function collectViewModesFromElements(
  elements: Iterable<HTMLElement>,
): Set<SunoViewMode> {
  const modes = new Set<SunoViewMode>();
  for (const element of elements) {
    if (!isVisible(element)) {
      continue;
    }
    const mode = normalizeViewModeLabel(element.textContent ?? "");
    if (mode !== "unknown") {
      modes.add(mode);
    }
  }
  return modes;
}

function singleModeOrUnknown(modes: Set<SunoViewMode>): SunoViewMode {
  if (modes.size !== 1) {
    return "unknown";
  }
  return Array.from(modes)[0];
}

function hasExactlyOneMatch(root: HTMLElement, selector: string): boolean {
  return root.querySelectorAll(selector).length === 1;
}

function hasListCardActions(root: HTMLElement): boolean {
  return (
    hasExactlyOneMatch(root, SELECT_CLIP_BTN_SELECTOR) &&
    hasExactlyOneMatch(root, REMIX_BTN_SELECTOR) &&
    hasExactlyOneMatch(root, EDIT_TITLE_BTN_SELECTOR)
  );
}

function hasWaveformCardActions(root: HTMLElement): boolean {
  return (
    hasExactlyOneMatch(root, SELECT_CLIP_BTN_SELECTOR) &&
    hasExactlyOneMatch(root, REMIX_BTN_SELECTOR)
  );
}

function hasGridCardActions(root: HTMLElement): boolean {
  return hasExactlyOneMatch(root, REMIX_BTN_SELECTOR);
}

function isAlternateViewCardBoundary(root: HTMLElement): boolean {
  return root.matches("article");
}

function isDocumentRootElement(root: HTMLElement): boolean {
  return root === document.body || root === document.documentElement;
}

function findArticleCardRoot(anchor: HTMLElement): HTMLElement | null {
  const article = anchor.closest<HTMLElement>("article");
  if (article && !isDocumentRootElement(article)) {
    return article;
  }
  return null;
}

/**
 * Remix btn（anchor）から clip card root を構造的に解決する（#866）。
 * 親方向へ walk し、「Select clip / Remix clip / Edit title を各 1 つずつ含む最寄り祖先」を返す。
 * Emotion class hash（`.e1yitp9f1` 等）には依存しない。複数 card を内包する container は各ボタンが
 * 2 つ以上になるため exactly-one 判定で除外され、各 card 境界で確定する。
 * 3 ボタンが揃う祖先が無ければ throw（fail-loud, req 8: silent に親 root を返さない）。
 */
export function findCardRoot(anchor: HTMLElement): HTMLElement {
  let el: HTMLElement | null = anchor.parentElement;
  let hiddenCandidate: HTMLElement | null = null;
  while (el) {
    if (
      !isDocumentRootElement(el) &&
      (hasListCardActions(el) ||
        (isAlternateViewCardBoundary(el) &&
          (hasWaveformCardActions(el) || hasGridCardActions(el))))
    ) {
      if (isVisible(el)) {
        return el;
      }
      hiddenCandidate = el;
    }
    el = el.parentElement;
  }
  if (hiddenCandidate) {
    return hiddenCandidate;
  }
  throw new Error(
    "clip card root を解決できません。現在の Suno ビューで card root と判断できる祖先が見つかりませんでした（Suno の DOM 変更の可能性）。",
  );
}

function hasAlternateInFlightSignal(card: HTMLElement): boolean {
  if (!isVisible(card)) {
    return false;
  }
  return (
    card.matches('[aria-busy="true"]') ||
    card.querySelector('[aria-busy="true"], [role="progressbar"]') !== null
  );
}

function hasClipIdentity(card: HTMLElement): boolean {
  return (
    card.querySelector(
      `${SELECT_CLIP_BTN_SELECTOR}, ${DESELECT_CLIP_BTN_SELECTOR}, ${REMIX_BTN_SELECTOR}, ${EDIT_TITLE_BTN_SELECTOR}`,
    ) !== null
  );
}

function hasCountSignal(card: HTMLElement): boolean {
  return (
    card.querySelector(REMIX_BTN_SELECTOR) !== null ||
    hasAlternateInFlightSignal(card)
  );
}

function findClipCandidateRoot(anchor: HTMLElement): HTMLElement | null {
  const article = findArticleCardRoot(anchor);
  if (article && hasClipIdentity(article)) {
    return article;
  }

  let current = anchor.parentElement;
  while (current) {
    if (isDocumentRootElement(current)) {
      return null;
    }
    if (hasClipIdentity(current)) {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

interface InFlightCandidates {
  inFlightCards: Set<HTMLElement>;
  clipCandidates: Set<HTMLElement>;
  uncountableCandidates: Set<HTMLElement>;
}

function collectInFlightCandidates(): InFlightCandidates {
  const anchors = document.querySelectorAll<HTMLElement>(
    `${SELECT_CLIP_BTN_SELECTOR}, ${DESELECT_CLIP_BTN_SELECTOR}, ${REMIX_BTN_SELECTOR}, ${EDIT_TITLE_BTN_SELECTOR}, [aria-busy="true"], [role="progressbar"]`,
  );
  const inFlightCards = new Set<HTMLElement>();
  const clipCandidates = new Set<HTMLElement>();
  const uncountableCandidates = new Set<HTMLElement>();
  for (const anchor of anchors) {
    const card = findClipCandidateRoot(anchor);
    if (!card || !isVisible(card) || !hasClipIdentity(card)) {
      continue;
    }
    clipCandidates.add(card);
    if (!hasCountSignal(card)) {
      uncountableCandidates.add(card);
      continue;
    }
    if (hasAlternateInFlightSignal(card)) {
      inFlightCards.add(card);
    }
  }
  return { inFlightCards, clipCandidates, uncountableCandidates };
}

/**
 * 1 つの clip card が「生成中」か判定する（#866）。
 * card 内 Remix btn が `disabled`（または `aria-disabled="true"`）なら生成中。音源が揃って初めて
 * Remix が押せるようになる Suno のドメインルールを利用する。strict isVisible() で card 自体も filter し、
 * 非可視 card（display:none / bbox 0 / 親 walk で隠れ）は生成中とみなさない。
 * Remix btn が card 内に無い場合は throw（fail-loud, req 8: silent に false を返さない）。
 */
export function isClipGenerating(card: HTMLElement): boolean {
  const remix = card.querySelector<HTMLButtonElement>(REMIX_BTN_SELECTOR);
  if (!remix) {
    throw new Error(
      "clip card 内に Remix btn がありません。card root の解決が誤っているか Suno の DOM 変更の可能性があります。",
    );
  }
  return (
    isVisible(card) &&
    (remix.disabled || remix.getAttribute("aria-disabled") === "true")
  );
}

/**
 * 生成中（in-flight）な clip 数を数える（#866）。
 * 全 Remix btn から findCardRoot で card root を解決して重複排除し、`isClipGenerating(card)`
 * （内部で `isVisible(card)` も判定）が true な distinct card 数を返す。
 * Remix btn が無い card は、aria-busy / progressbar の明示シグナルがある場合だけ union して数える。
 * clip 候補自体が無く、現在ビューを検出できる場合だけ空 queue として 0 を返す。
 */
export function getInFlightClipCount(): number {
  const anchors =
    document.querySelectorAll<HTMLButtonElement>(REMIX_BTN_SELECTOR);
  const cards = new Set<HTMLElement>();
  for (const anchor of anchors) {
    const card = findCardRoot(anchor);
    if (isClipGenerating(card)) {
      cards.add(card);
    }
  }
  const candidates = collectInFlightCandidates();
  if (candidates.uncountableCandidates.size > 0) {
    throw new Error(
      "clip 候補に Remix btn も代替の生成中シグナルも見つかりません。in-flight 検知が不能です（Suno の DOM 変更の可能性）。",
    );
  }
  for (const card of candidates.inFlightCards) {
    cards.add(card);
  }
  if (anchors.length === 0 && cards.size === 0) {
    if (
      candidates.clipCandidates.size === 0 &&
      detectSunoViewMode() !== "unknown"
    ) {
      return 0;
    }
    throw new Error(
      "Remix btn が 1 件も見つからず、clip 候補に代替の生成中シグナルも見つかりません。in-flight 検知が不能です（Suno の DOM 変更の可能性）。",
    );
  }
  return cards.size;
}

/**
 * in-flight clip 数が `maxClips` 未満になるまで poll で待機する（#816, #847, #948）。
 *   - isAborted() が true なら（toast 中・上限超でも）最優先で即 resolve（throw しない）
 *   - queue 上限エラー toast 表示中は、空きスロットがあっても投入せず待機を継続する（#847）
 *   - toast が消えたら `queueErrorWaitMs` の安全マージンを待ってから判定を再開する（#847）
 *   - in-flight < maxClips になったら resolve（投入再開）
 *   - 終了判定は 2 経路 (#948):
 *       - stall 経路（getLastChangeAt 注入時）: in-flight 集合が「待機開始 or 最終変化」から
 *         stallTimeoutMs 変化しないときのみ throw。正確なカウントの下では上限での長い待ちは
 *         正常状態（clip 完了に数分かかる）のため、固定 deadline は誤停止になる
 *       - 固定 deadline 経路（従来互換）: timeoutMs 超過で timeout throw
 * Suno は同時 10 リクエスト = 20 clip までしか積めず、超過すると後続が silent fail するため、
 * 各リクエスト投入前にこの関数で空きスロットを待つ。Create→clip card DOM 反映ラグで Suno が投入を
 * reject すると toast が出るため、toast 検知中は投入を止め、消失後に buffer を取ってから再開する。
 */
export async function waitForQueueSlot(
  maxClips: number,
  options: WaitForQueueSlotOptions,
): Promise<void> {
  const getCount = options.getCount ?? getInFlightClipCount;
  const startAt = Date.now();
  const deadline = startAt + options.timeoutMs;
  const stallTimeoutMs = options.stallTimeoutMs ?? options.timeoutMs;
  let sawQueueError = false;
  for (;;) {
    if (options.isAborted()) {
      return;
    }
    // 終了判定はループ先頭で行う（toast が出続ける経路でも必ず到達する）。
    if (options.getLastChangeAt) {
      // stall 経路: 観測 clip の status 遷移（submitted→queued→streaming→complete）が続く限り
      // 待ち続ける。集合が完全に固まったときのみ「Suno 側の停滞」として fail-loud。
      const lastActivity = Math.max(startAt, options.getLastChangeAt());
      if (Date.now() - lastActivity >= stallTimeoutMs) {
        throw new FatalRunError(
          `生成キューの空き待ち中、in-flight の状態が ${Math.round(stallTimeoutMs / 60000)} 分間変化しませんでした。Suno 側で生成が停滞している可能性があります。`,
        );
      }
    } else if (Date.now() >= deadline) {
      throw new FatalRunError(
        "生成キューの空きスロット待ちがタイムアウトしました。",
      );
    }
    if (isQueueLimitErrorVisible()) {
      // toast 中はスロットが空いていても投入しない。消失を待つ。
      sawQueueError = true;
      await sleep(options.pollIntervalMs);
      continue;
    }
    if (sawQueueError) {
      // toast が消えた直後は反映ラグが残るため、安全マージンを取ってから判定を再開する。
      // buffer 待機中の停止押下にも 3 秒以内で反応できるよう中断可能な abortableSleep を使う（#847）。
      sawQueueError = false;
      await abortableSleep(options.queueErrorWaitMs, options.isAborted);
      continue;
    }
    if (getCount() < maxClips) {
      return;
    }
    await sleep(options.pollIntervalMs);
  }
}

/**
 * pointer + mouse イベントシーケンスで要素をクリックする。
 * Suno 2026-06: 一部ボタン（More options 等）は click イベントだけでは反応せず
 * pointerdown → mousedown → pointerup → mouseup → click の完全シーケンスが必要。
 */
export function simulateClick(el: HTMLElement): void {
  const rect = el.getBoundingClientRect();
  const x = rect.x + rect.width / 2;
  const y = rect.y + rect.height / 2;
  const shared = {
    bubbles: true,
    cancelable: true,
    clientX: x,
    clientY: y,
    button: 0,
  };
  el.dispatchEvent(
    new PointerEvent("pointerdown", { ...shared, pointerId: 1 }),
  );
  el.dispatchEvent(new MouseEvent("mousedown", shared));
  el.dispatchEvent(new PointerEvent("pointerup", { ...shared, pointerId: 1 }));
  el.dispatchEvent(new MouseEvent("mouseup", shared));
  el.dispatchEvent(new MouseEvent("click", shared));
}
