// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行 (content script)。
// DOM 操作は shared/dom の純関数へ委譲し、本ファイルは連続実行のフロー制御に専念する。
import type { DurationFilter, PromptEntry } from "../../shared/api";
import {
  BALANCED_RUN_PACING,
  CLIPS_PER_REQUEST,
  INFLIGHT_STALL_TIMEOUT_MS,
  PHASE,
  type ProgressPayload,
  QUEUE_ERROR_WAIT_MS,
  QUEUE_SLOT_WAIT_TIMEOUT_MS,
  type SnapshotPayload,
  SUNO_MATCHES,
} from "../../shared/constants";
import { applyProgress, initSnapshot } from "../lib/snapshot";
import { applyJitter } from "../lib/preset-state";
import {
  clearResumeStateForCollection,
  resolvePlaylistClipIds,
  resolveInterruptIndex,
  type RunRange,
  writeResumeState,
} from "../lib/resume-state";
import { InjectNotAcknowledgedError, injectWithVerification } from "../lib/inject-retry";
import { runEntryWithRetry } from "../lib/entry-retry";
import { createAckWaiter, markAck } from "../lib/ack-probe";
import { attachBridgeListener, createFeedPoller, requestFeedPoll, requestSliderSet } from "../lib/bridge-listener";
import { createClipTracker } from "../lib/clip-tracker";
import { createDownloadFlow } from "../lib/download-flow";
import {
  abortableSleep,
  CAPTCHA_WAIT_TIMEOUT_MS,
  FatalRunError,
  GENERATE_TIMEOUT_MS,
  POLL_INTERVAL_MS,
  SETTLE_MS,
  detectSunoViewMode,
  getInFlightClipCount,
  injectAdvancedFields,
  resolveAdvancedFields,
  resolveFields,
  resolveGenerateButton,
  setLyricsValue,
  setNativeValue,
  sleep,
  waitForCaptchaClear,
  waitForGeneration,
  waitForQueueSlot,
} from "../../shared/dom";
import {
  clickPlaylistRowByName,
  fillPlaylistNameAndCreate,
  openAddToPlaylistDialogViaCmdP,
  readSelectedClipIds,
  scrollAndMultiSelectByIds,
  waitForPlaylistDialogClose,
} from "../../shared/playlist-dom";
import { onMessage, sendMessage } from "../lib/messaging";
import type { RetryDownloadPayload, RetryPlaylistPayload, RunPayload } from "../lib/messaging";
import { clearFinishedSnapshot, readFreshFinishedSnapshot, writeFinishedSnapshot } from "../lib/finished-snapshot";
import { cancelScheduledRunCompleteReload, scheduleRunCompleteReload } from "../lib/page-reload";
import { readDownloadFormat, serverUrlItem } from "../lib/storage";
import type { DownloadContext } from "../lib/download-flow";

function assertNonEmptyString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${field} must be non-empty string`);
  }
  return value;
}

function assertRecord(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${field} must be object`);
  }
  return value as Record<string, unknown>;
}

function assertStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${field} must be string array`);
  }
  return value;
}

function assertOptionalFiniteNumber(value: unknown, field: string): number | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${field} must be finite number`);
  }
  return value;
}

function assertOptionalBoolean(value: unknown, field: string): boolean | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (typeof value !== "boolean") {
    throw new Error(`${field} must be boolean`);
  }
  return value;
}

function assertOptionalDurationFilter(value: unknown, field: string): DurationFilter | undefined {
  if (value === undefined) {
    return undefined;
  }
  const record = assertRecord(value, field);
  const minSec = assertOptionalFiniteNumber(record.min_sec, `${field}.min_sec`);
  const maxSec = assertOptionalFiniteNumber(record.max_sec, `${field}.max_sec`);
  if (minSec === undefined || maxSec === undefined) {
    throw new Error(`${field}.min_sec and ${field}.max_sec are required`);
  }
  if (minSec < 0 || maxSec < 0) {
    throw new Error(`${field}.min_sec and ${field}.max_sec must be non-negative`);
  }
  if (minSec > maxSec) {
    throw new Error(`${field}.min_sec must be less than or equal to max_sec`);
  }
  return { min_sec: minSec, max_sec: maxSec };
}

function assertOptionalIndices(value: unknown, field: string, entryCount: number): number[] | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (!Array.isArray(value)) {
    throw new Error(`${field} must be number array`);
  }
  if (value.length === 0) {
    throw new Error(`${field} must not be empty`);
  }
  const seen = new Set<number>();
  return value.map((item, index) => {
    if (typeof item !== "number" || !Number.isInteger(item)) {
      throw new Error(`${field}[${index}] must be integer`);
    }
    if (item < 0 || item >= entryCount) {
      throw new Error(`${field}[${index}] must be within entries range`);
    }
    if (seen.has(item)) {
      throw new Error(`${field}[${index}] must be unique`);
    }
    seen.add(item);
    return item;
  });
}

function assertRunPayload(value: unknown): RunPayload {
  const record = assertRecord(value, "run payload");
  if (!Array.isArray(record.entries)) {
    throw new Error("run.entries must be array");
  }
  return {
    ...(record as unknown as RunPayload),
    entries: record.entries as PromptEntry[],
    playlistName: assertNonEmptyString(record.playlistName, "run.playlistName"),
    collectionId: assertNonEmptyString(record.collectionId, "run.collectionId"),
    durationFilter: assertOptionalDurationFilter(record.durationFilter, "run.durationFilter"),
    indices: assertOptionalIndices(record.indices, "run.indices", record.entries.length),
  };
}

function assertRetryPlaylistPayload(value: unknown): RetryPlaylistPayload {
  const record = assertRecord(value, "retryPlaylist payload");
  return {
    playlistName: assertNonEmptyString(record.playlistName, "retryPlaylist.playlistName"),
    submittedClipIds: assertStringArray(record.submittedClipIds, "retryPlaylist.submittedClipIds"),
    expectedClipCount: assertOptionalFiniteNumber(record.expectedClipCount, "retryPlaylist.expectedClipCount") ?? 0,
    collectionId: assertNonEmptyString(record.collectionId, "retryPlaylist.collectionId"),
    shouldDownload: assertOptionalBoolean(record.shouldDownload, "retryPlaylist.shouldDownload"),
  };
}

function assertRetryDownloadPayload(value: unknown): RetryDownloadPayload {
  const record = assertRecord(value, "retryDownload payload");
  return {
    collectionId: assertNonEmptyString(record.collectionId, "retryDownload.collectionId"),
    submittedClipIds: assertStringArray(record.submittedClipIds, "retryDownload.submittedClipIds"),
    expectedClipCount: assertOptionalFiniteNumber(record.expectedClipCount, "retryDownload.expectedClipCount"),
  };
}

function buildTitleFallbackMap(entries: PromptEntry[], order: number[], submittedIds: string[]): Map<string, string> {
  const map = new Map<string, string>();
  for (let i = 0; i < order.length; i++) {
    const entry = entries[order[i]];
    if (!entry) continue;
    const title = entry.title ?? entry.name;
    const clipBase = i * CLIPS_PER_REQUEST;
    for (let c = 0; c < CLIPS_PER_REQUEST; c++) {
      const clipId = submittedIds[clipBase + c];
      if (clipId) {
        map.set(clipId, title);
      }
    }
  }
  return map;
}

async function resolveDownloadContext(): Promise<DownloadContext> {
  return {
    baseUrl: (await serverUrlItem.getValue()).trim(),
    format: await readDownloadFormat(),
  };
}

export default defineContentScript({
  matches: [...SUNO_MATCHES],
  main() {
    let aborted = false;
    // 連続実行の二重起動ガード (#892 要件7)。runAll 実行中の run 再着信を弾く。
    let running = false;
    // 直近の injectAndGenerate で Generate を click した entry の 0-based index (#924)。
    // -1 は「まだ click していない」。中断時に submitted 判定と組み合わせて interruptIndex を決定する。
    // run ハンドラで -1 にリセットし、injectAndGenerate の冒頭でも attempt ごとにリセットする（理由は同関数コメント参照）。
    let lastSubmittedEntryIndex = -1;
    // popup を閉じても進捗を維持・復元するための SSOT (#852)。run 開始で initSnapshot、
    // 以降は emitProgress が sendMessage より前に同期更新する（queryProgress と race しないため）。
    let currentSnapshot: SnapshotPayload | null = null;

    // bridge（MAIN world）の観測を集約する in-flight の SSOT (#948)。run の外でも常時受信し、
    // run 前のページ操作（手動投入等）や前 run の残留 in-flight も passive 合流で数える。
    const tracker = createClipTracker();
    attachBridgeListener(tracker);
    // status 更新は WebSocket 経由でページの feed fetch を期待できないため、run 中は
    // 未終端 clip がある限り active feed poll で status を追う（runAll の finally で stop）。
    const feedPoller = createFeedPoller(tracker);
    let warnedDomFallback = false;

    /** in-flight 数の合成カウント (#948)。bridge 観測があれば status ベース、無ければ DOM プロキシへ縮退。 */
    function currentInFlightCount(): number {
      if (tracker.hasObservedAnyTraffic()) {
        return tracker.getInFlightCount();
      }
      if (!warnedDomFallback) {
        warnedDomFallback = true;
        console.warn(
          "[suno-helper] bridge 未観測のため DOM プロキシで in-flight を数えます（過大カウントの可能性あり）",
        );
      }
      return getInFlightClipCount();
    }

    /** inject ACK のハイブリッド判定 (#948)。bridge の generate レスポンス観測 OR DOM 増分。 */
    const waitForAck = createAckWaiter({
      getSubmissionCount: () => tracker.submissionCount(),
      getDomInFlightCount: getInFlightClipCount,
      sleep,
    });

    function emitProgress(payload: ProgressPayload): void {
      if (!currentSnapshot) {
        // run ハンドラで initSnapshot 済みのため到達しない。万一来たら不変条件違反として fail-loud。
        throw new Error("progress emit before run initialization");
      }
      currentSnapshot = applyProgress(currentSnapshot, payload);
      void sendMessage("progress", payload);
    }

    function entryDisplayName(entry: PromptEntry): string {
      return entry.title ?? entry.name;
    }

    /**
     * 完了時リロード (#1411) の直前に FINISHED snapshot を chrome.storage.local へ退避する。
     * リロードは in-memory の currentSnapshot（queryProgress の復元 SSOT, #852）を破棄するため、
     * run 中に popup を閉じていた運用者が再 open しても完了結果を確認できるよう引き継ぐ。
     * 退避に失敗したら false を返し、呼び出し側はリロードを見送る（in-memory snapshot が
     * 生き残るため復元性は保たれる。残る stale selection は次 run の Cmd+P 前ガードが検知する —
     * resume state 消去失敗時と同じ扱い）。
     */
    async function persistFinishedSnapshotForReload(): Promise<boolean> {
      if (!currentSnapshot) {
        // FINISHED emit 済みの経路からのみ呼ばれるため到達しない（emitProgress と同じ不変条件）。
        return false;
      }
      try {
        await writeFinishedSnapshot({ snapshot: currentSnapshot, timestamp: Date.now() });
        return true;
      } catch (err) {
        console.warn("[suno-helper] 完了 snapshot の退避に失敗しました。完了時リロードを見送ります:", err);
        return false;
      }
    }

    const downloadFlow = createDownloadFlow({
      emitProgress,
      isAborted: () => aborted,
    });
    downloadFlow.installMessageHandlers();

    async function injectAndGenerate(entry: PromptEntry, index: number, total: number): Promise<void> {
      // attempt ごとに lastSubmittedEntryIndex を -1 にリセットする。
      // injectWithVerification が silent drop を検知して同一 entry を retry するとき、
      // 前 attempt の click が lastSubmittedEntryIndex に残っていると「投入済み」と誤判定し、
      // retry 中に captcha throw が来た場合に当該 entry を skip するバグ（欠落）を防ぐ (#924)。
      lastSubmittedEntryIndex = -1;
      const { style, lyrics, title } = resolveFields();
      setNativeValue(style, entry.style);
      if (lyrics) {
        // 空文字でも上書きする。instrumental パターン (entry.lyrics === "") のとき前パターンの歌詞を残さない。
        await setLyricsValue(lyrics, entry.lyrics);
      } else if (entry.lyrics) {
        // 歌詞があるのに Lyrics 欄が見つからないのは設定不整合。silent に飛ばさず停止する。
        // 設定不整合は全 entry で再発するため fatal（entry retry の対象外）。
        throw new FatalRunError(
          "Lyrics 欄が見つかりません。Instrumental OFF（Custom Mode）になっているか確認してください。",
        );
      }
      if (title) {
        // Song Title は entry.title 優先、無ければ entry.name で代替する (#844)。
        setNativeValue(title, entry.title ?? entry.name);
      } else {
        // title 欄不在は Suno 側 UI 改装の可能性。style/lyrics と違い fail-soft（警告のみで続行）。
        console.warn("Song Title 欄が見つかりませんでした。タイトル注入を skip して続行します。");
      }
      // Custom Mode > More Options の 3 フィールド (#900)。slider 注入は MAIN world bridge 経由
      // （React onKeyDown 直接呼び出しで isTrusted チェックを通過、#973）を優先し、失敗時は従来の
      // 合成 keydown dispatch へ縮退する（e2e mock の plain DOM はこちらで動く）。entry に値があり
      // selector が不在なら injectAdvancedFields が throw する (fail-loud)。値が無ければ skip する
      // (fail-soft、後方互換)。
      await injectAdvancedFields(entry, resolveAdvancedFields(), {
        bridgeSetSlider: requestSliderSet,
      });
      await abortableSleep(SETTLE_MS, () => aborted);

      if (aborted) {
        return; // 停止押下後は Generate を押さない（未投入のまま STOPPED 経路へ）
      }

      // captcha が出ていても即停止しない。多くは passive 検証で数秒以内に自動 verify されて閉じるため、
      // waiting-captcha phase で解消を待って自動続行する。解消されない場合のみ throw（fail-loud は維持）。
      await waitForCaptchaClear({
        isAborted: () => aborted,
        pollIntervalMs: POLL_INTERVAL_MS,
        timeoutMs: CAPTCHA_WAIT_TIMEOUT_MS,
        onWaitStart: () => emitProgress({ phase: PHASE.WAITING_CAPTCHA, index, total }),
      });
      if (aborted) {
        return; // captcha 解消待ち中の停止。Generate を押さない（未投入のまま STOPPED 経路へ）
      }

      const button = resolveGenerateButton();
      button.click();
      // Generate click 直後に lastSubmittedEntryIndex を更新する。中断時の interruptIndex 計算で
      // 「この entry は click 済み（submitted）」と判定できるようにする (#924)。
      lastSubmittedEntryIndex = index;
      // Generate 押下後は最大 GENERATE_TIMEOUT_MS の生成完了待ちに入る。注入中と区別して表示する。
      emitProgress({ phase: PHASE.GENERATING, index, total });
      await waitForGeneration(button, {
        isAborted: () => aborted,
        timeoutMs: GENERATE_TIMEOUT_MS,
        pollIntervalMs: POLL_INTERVAL_MS,
        settleMs: SETTLE_MS,
        captchaWaitTimeoutMs: CAPTCHA_WAIT_TIMEOUT_MS,
        // 生成完了待ち中に captcha が出たら waiting-captcha 表示へ切り替え、解消後 generating へ戻す。
        onCaptchaWait: (waiting) =>
          emitProgress({ phase: waiting ? PHASE.WAITING_CAPTCHA : PHASE.GENERATING, index, total }),
      });
    }

    /**
     * 全 clip を multi-select → Cmd+P で Add to Playlist dialog → 名前注入 → Create Playlist の一連を実行する (#854)。
     * 各ステップ間に abortableSleep を挟み、停止押下に素早く反応する。
     */
    async function addClipsToPlaylist(
      progressTotal: number,
      playlistName: string,
      previousSubmittedClipIds: string[],
      expectedClipCount: number,
      entries: PromptEntry[],
      order: number[],
    ): Promise<number> {
      emitProgress({ phase: PHASE.ADDING_TO_PLAYLIST, total: progressTotal, message: playlistName });
      const currentSubmittedIds = tracker.getSubmittedIds();
      const allSubmittedIds = [...previousSubmittedClipIds, ...currentSubmittedIds];
      const observedCount = new Set(allSubmittedIds).size;
      if (observedCount !== expectedClipCount) {
        console.warn(
          `[suno-helper] bridge observation gap: expected ${expectedClipCount} clip IDs, observed ${observedCount}`,
        );
      }
      const submittedIds = resolvePlaylistClipIds(previousSubmittedClipIds, currentSubmittedIds, expectedClipCount);
      const currentTitleFallbackMap = buildTitleFallbackMap(entries, order, currentSubmittedIds);
      const currentOrder = new Set(order);
      const previousOrder = entries.map((_, index) => index).filter((index) => !currentOrder.has(index));
      const previousTitleFallbackMap = buildTitleFallbackMap(entries, previousOrder, previousSubmittedClipIds);
      const titleFallbackMap = new Map([...previousTitleFallbackMap, ...currentTitleFallbackMap]);
      const selectedCount = await scrollAndMultiSelectByIds(submittedIds, {
        isAborted: () => aborted,
        titleFallbackMap,
      });
      if (aborted) {
        return selectedCount;
      }
      if (selectedCount !== expectedClipCount) {
        throw new Error(
          `playlist 対象の DOM 選択数が一致しません: expected ${expectedClipCount}, selected ${selectedCount}`,
        );
      }
      await abortableSleep(SETTLE_MS, () => aborted);
      if (aborted) {
        return selectedCount;
      }

      // Cmd+P 直前の保険ガード (#1411 要件4)。完了時リロードが走らなかった経路（クラッシュ等）で
      // 前回 run の stale selection が残っていると、Cmd+P は選択中 clip 全件を playlist 追加対象に
      // するため累積汚染される。実際の選択中 clip を読み取り、target 件数を超えていたら fail-loud で
      // 中断する。判定は件数比較にする: scrollAndMultiSelectByIds の title fallback で選択した row は
      // DOM 上の ID が target 集合に含まれないため、ID 集合差だと誤検知する。
      // 走査は 1 pass + 超過検知での即打ち切りに絞る（クリーンな happy path で毎 run 全 3 pass の
      // コストを払わない）。ガード自身の走査失敗（scroller 不在・render flake での 0 件等）は、
      // 生成完了済みの run を巻き添えにしないため fail-open（警告して続行）とする。
      let actualSelectedIds: string[] | null = null;
      try {
        actualSelectedIds = await readSelectedClipIds({
          isAborted: () => aborted,
          maxScanPasses: 1,
          stopAboveCount: expectedClipCount,
          skipUnresolvedIds: true,
        });
      } catch (err) {
        if (!aborted) {
          console.warn("[suno-helper] stale selection ガードの走査に失敗したためスキップして続行します:", err);
        }
      }
      if (aborted) {
        return selectedCount;
      }
      if (actualSelectedIds !== null && actualSelectedIds.length > expectedClipCount) {
        const targetIdSet = new Set(submittedIds);
        const extraIds = actualSelectedIds.filter((id) => !targetIdSet.has(id));
        throw new Error(
          `選択中 clip が playlist 対象より多く、前回実行の選択が残っている可能性があります` +
            `（expected ${expectedClipCount}, selected ${actualSelectedIds.length}）。` +
            `ページをリロードして選択状態を解除してから再実行してください。` +
            `参考: target 集合外の選択中 ID（title fallback で選択した正当な clip を含む場合があります）: ${extraIds.join(", ")}`,
        );
      }

      const isMac = navigator.platform.toLowerCase().includes("mac");
      const dialog = await openAddToPlaylistDialogViaCmdP(async () => {
        await sendMessage("sendTrustedCmdP", { isMac });
      });
      await abortableSleep(SETTLE_MS, () => aborted);

      await fillPlaylistNameAndCreate(dialog, playlistName);
      // Suno の Cmd+P dialog 仕様: Create Playlist は空 playlist を作るだけで、
      // 選択中 clip は追加されない。dialog 内 list に出現した新規 row を改めて click して
      // clip を紐付ける（同名 row が複数並ぶ場合は DOM 順で最後 = 直前作成分を選ぶ）。
      await abortableSleep(SETTLE_MS, () => aborted);
      await clickPlaylistRowByName(dialog, playlistName);
      await waitForPlaylistDialogClose({
        isAborted: () => aborted,
        pollIntervalMs: POLL_INTERVAL_MS,
        timeoutMs: GENERATE_TIMEOUT_MS,
      });
      return selectedCount;
    }

    async function waitForSubmittedClipsComplete(
      expectedClipCount: number,
      previousSubmittedClipIds: string[],
      isAborted: () => boolean,
    ): Promise<string[]> {
      const deadline = Date.now() + INFLIGHT_STALL_TIMEOUT_MS;
      let lastPendingCount = Number.POSITIVE_INFINITY;
      while (!isAborted()) {
        const submittedIds = tracker.getSubmittedIds();
        const observedSubmittedCount = new Set([...previousSubmittedClipIds, ...submittedIds]).size;
        const pendingSubmittedIds = tracker.getPendingSubmittedIds();
        if (observedSubmittedCount >= expectedClipCount && pendingSubmittedIds.length === 0) {
          return submittedIds;
        }
        if (pendingSubmittedIds.length === 0) {
          throw new Error(
            `playlist 対象の clip ID 数が不足しています: expected ${expectedClipCount}, got ${observedSubmittedCount}`,
          );
        }
        if (pendingSubmittedIds.length !== lastPendingCount) {
          lastPendingCount = pendingSubmittedIds.length;
          console.info(
            `[suno-helper] final clip completion wait: submitted=${observedSubmittedCount}/${expectedClipCount}, pending=${pendingSubmittedIds.length}`,
          );
        }
        if (Date.now() >= deadline) {
          throw new Error(
            `生成完了待ちがタイムアウトしました: submitted=${observedSubmittedCount}/${expectedClipCount}, pending=${pendingSubmittedIds.length}`,
          );
        }
        if (pendingSubmittedIds.length > 0) {
          await requestFeedPoll(pendingSubmittedIds);
        }
        await abortableSleep(POLL_INTERVAL_MS, isAborted);
      }
      return tracker.getSubmittedIds();
    }

    interface RunOptions {
      // collection 単位 duration guard 閾値 (#1259)。実フィルタは yield guard 側で消費する。
      durationFilter?: DurationFilter;
      // 0-based inclusive な実行範囲 (#872)。未指定は全 entry。判断A: range 指定でも entries 全体と
      // 絶対 index を保ち、range 内の entry だけを処理する（slice 再採番による index ズレを起こさない）。
      range?: RunRange;
      // ERROR 停止時に resume state を紐付ける collection 識別子 (#872)。
      collectionId: string;
      // collection mode のときの playlist 名 (#854)。全 entry 完了後の clip 一括追加に使う。
      playlistName: string;
      // 任意の部分実行対象の 0-based index 列。チェック選択や失敗分再実行で使う。指定時は range より優先。
      indices?: number[];
      // 再開前の run で観測済みの playlist 対象 clip ID。
      submittedClipIds?: string[];
      // playlist 追加時に揃っているべき clip ID 件数。
      playlistExpectedClipCount?: number;
    }

    async function runAll(entries: PromptEntry[], options: RunOptions): Promise<void> {
      const { range, collectionId, playlistName, submittedClipIds, playlistExpectedClipCount } = options;
      const previousSubmittedClipIds = submittedClipIds ?? [];
      const pacing = BALANCED_RUN_PACING;
      // Suno 同時生成キューに積める clip 数の上限（Balanced の並列リクエスト数 × 2 clip）。
      const maxGeneratingClips = pacing.maxInflightRequests * CLIPS_PER_REQUEST;
      const total = entries.length;
      if (total === 0) {
        emitProgress({ phase: PHASE.FINISHED, total });
        return;
      }
      const startIndex = range ? range.start : 0;
      const endIndex = range ? range.end : total - 1;
      // 実行対象の 0-based index 列。indices（チェック選択/失敗分再実行）が最優先、無ければ range 由来。
      const order = options.indices ?? Array.from({ length: endIndex - startIndex + 1 }, (_, k) => startIndex + k);
      const hasExplicitIndices = options.indices !== undefined;
      const expectedPlaylistClipCount =
        playlistExpectedClipCount ??
        (order.length === 0
          ? total * CLIPS_PER_REQUEST
          : new Set(previousSubmittedClipIds).size + order.length * CLIPS_PER_REQUEST);
      // リトライ上限まで失敗しスキップした entry の 0-based index (#948)。終了時に resume state へ
      // 永続化し、popup の「失敗分のみ再実行」導線が消費する。
      const failedIndices: number[] = [];
      let keepResumeStateForDownloadRetry = false;
      // 中断 entry を永続化し、reload 後の ResumeBanner で続きから再開できるようにする。
      // ERROR phase (#872 要件3) と STOPPED phase (#898 要件1/2/3) の共通処理。failedIndex 名は
      // そのまま流用し (要件3)、中断 index を載せる。
      // スキップ済み failedIndices があれば一緒に永続化する (#948)。
      function persistInterruptState(interruptedIndex: number, orderPosition?: number): void {
        const remainingIndices =
          hasExplicitIndices && orderPosition !== undefined
            ? order.slice(interruptedIndex === order[orderPosition] ? orderPosition : orderPosition + 1)
            : undefined;
        const persistedSubmittedClipIds = Array.from(
          new Set([...previousSubmittedClipIds, ...tracker.getSubmittedIds()]),
        );
        currentSnapshot =
          currentSnapshot === null
            ? currentSnapshot
            : {
                ...currentSnapshot,
                failedIndex: interruptedIndex,
                remainingIndices,
                submittedClipIds: persistedSubmittedClipIds,
                playlistExpectedClipCount: expectedPlaylistClipCount,
              };
        void writeResumeState({
          collectionId,
          failedIndex: interruptedIndex,
          total,
          timestamp: Date.now(),
          failedIndices: failedIndices.length > 0 ? [...failedIndices] : undefined,
          remainingIndices,
          submittedClipIds: persistedSubmittedClipIds,
          playlistExpectedClipCount: expectedPlaylistClipCount,
        });
      }
      for (const [orderPosition, i] of order.entries()) {
        if (aborted) {
          // ループ先頭の中断: この時点でまだ Generate を click していないため i をそのまま使う (#924)。
          persistInterruptState(i, orderPosition);
          emitProgress({ phase: PHASE.STOPPED, index: i, total });
          return;
        }
        // 1 entry の実行を失敗分類つきで包む (#948)。一時的な失敗は Balanced の maxEntryRetry 回まで
        // 同一 entry を再試行し、それでも失敗ならスキップして次へ（run 全体は止めない）。
        const result = await runEntryWithRetry({
          attempt: async () => {
            // Suno のキュー上限（20 clip）を超えると後続が silent fail するため、投入前に空きを待つ。
            // bridge 無観測の縮退中は message で明示する (#948 PR4: DOM プロキシは過大カウントしうるため
            // 「待ちが長い」原因をユーザーが切り分けられるようにする)。
            emitProgress({
              phase: PHASE.WAITING_SLOT,
              index: i,
              total,
              message: tracker.hasObservedAnyTraffic() ? undefined : "bridge 未観測: DOM 計数で待機中",
            });
            await waitForQueueSlot(maxGeneratingClips, {
              isAborted: () => aborted,
              pollIntervalMs: POLL_INTERVAL_MS,
              // getLastChangeAt 注入により stall 経路で動くため timeoutMs は実質未使用（後方互換用に残す）。
              timeoutMs: QUEUE_SLOT_WAIT_TIMEOUT_MS,
              queueErrorWaitMs: QUEUE_ERROR_WAIT_MS,
              // bridge の status ベースカウント (#948)。Remix disabled プロキシは完了後も disabled が
              // 残り過大カウントするため、観測があれば一次情報（API status）で数える。
              getCount: currentInFlightCount,
              // stall ベース判定 (#948): 正確なカウントの下では上限での長い待ちは正常状態
              //（clip 完了に数分かかる）。固定 5 分 deadline は誤停止になるため、
              // 「in-flight 集合が 10 分間まったく変化しない」ときのみ fail-loud に倒す。
              getLastChangeAt: () => tracker.lastChangeAt(),
              stallTimeoutMs: INFLIGHT_STALL_TIMEOUT_MS,
            });
            if (aborted) {
              return; // 中断は直後の outcome 判定で STOPPED 経路へ
            }
            emitProgress({ phase: PHASE.INJECTING, index: i, total });
            // inject 後に受理（ACK）を検証し、silent drop なら同じ entry を retry する (#864 root cause 3)。
            // ACK は bridge の generate レスポンス観測 OR DOM 増分のハイブリッド (#948)。
            await injectWithVerification({
              inject: () => injectAndGenerate(entries[i], i, total),
              markBeforeInject: () =>
                markAck({
                  getSubmissionCount: () => tracker.submissionCount(),
                  getDomInFlightCount: getInFlightClipCount,
                  sleep,
                }),
              waitForAck,
              isAborted: () => aborted,
              maxRetry: pacing.maxInjectRetry,
              ackTimeoutMs: pacing.injectAckTimeoutMs,
              pollIntervalMs: POLL_INTERVAL_MS,
              describeEntry: () => `entry ${i} (${entries[i].title ?? entries[i].name})`,
            });
          },
          isAborted: () => aborted,
          // Generate click 済みで受理失敗確定でないエラー（典型: 生成完了待ち timeout）は再実行すると
          // 重複生成になるため presumed-done（resolveInterruptIndex の i+1 判断と同じ）。
          wasSubmitted: (err) => lastSubmittedEntryIndex === i && !(err instanceof InjectNotAcknowledgedError),
          isFatal: (err) => err instanceof FatalRunError,
          maxRetry: pacing.maxEntryRetry,
          retryDelayMs: () => applyJitter(pacing.interCreateDelayMs, pacing.jitterMs),
          onRetry: (attempt, max) =>
            emitProgress({
              phase: PHASE.WAITING_SLOT,
              index: i,
              total,
              log: { kind: "retry", entryName: entryDisplayName(entries[i]), attempt, max },
            }),
          sleep: abortableSleep,
          describeEntry: () => `entry ${i} (${entries[i].title ?? entries[i].name})`,
        });
        if (result.outcome === "fatal") {
          const message = result.error instanceof Error ? result.error.message : String(result.error);
          // interruptIndex: submitted（Generate click 済み）かつ silent drop 確定でない → i+1（重複しない）。
          // emitProgress の index も interruptIndex にする: snapshot.applyProgress が ERROR payload の
          // index を failedIndex として記録し、popup が chrome.storage 喪失時の冗長ソースに使うため (#924)。
          const interruptIndex = resolveInterruptIndex(
            i,
            lastSubmittedEntryIndex === i,
            result.error instanceof InjectNotAcknowledgedError,
          );
          emitProgress({ phase: PHASE.ERROR, index: interruptIndex, total, message });
          persistInterruptState(interruptIndex, orderPosition);
          return;
        }
        if (result.outcome === "aborted" || aborted) {
          // attempt 中の中断（waitForQueueSlot / injectAndGenerate 内の silent return 含む）。
          // Generate click 済みなら i+1 を persist し再開時の重複生成を防ぐ (#924)。
          const interruptIndex = resolveInterruptIndex(i, lastSubmittedEntryIndex === i, false);
          persistInterruptState(interruptIndex, orderPosition);
          emitProgress({ phase: PHASE.STOPPED, index: interruptIndex, total });
          return;
        }
        if (result.outcome === "failed") {
          const message = result.error instanceof Error ? result.error.message : String(result.error);
          failedIndices.push(i);
          console.warn(`[suno-helper] entry ${i} をスキップして続行します: ${message}`);
          emitProgress({
            phase: PHASE.ENTRY_FAILED,
            index: i,
            total,
            message,
            log: { kind: "skip", entryName: entryDisplayName(entries[i]) },
          });
          continue; // run 全体は止めない。retry 間で既に間隔を空けているため即次 entry へ。
        }
        if (result.outcome === "presumed-done") {
          const message = result.error instanceof Error ? result.error.message : String(result.error);
          console.warn(`[suno-helper] entry ${i} は投入済みのため生成済み扱いで続行します: ${message}`);
        }
        emitProgress({ phase: PHASE.DONE, index: i, total });
        // Create→clip-row DOM 反映ラグによる過剰投入 (race) を避けるため、次の投入前に間隔を空ける (#847)。
        // Balanced の基準間隔に ±jitter を加えて bot 判定の固定間隔シグナルを消す。毎回 fresh 算出する。
        await abortableSleep(applyJitter(pacing.interCreateDelayMs, pacing.jitterMs), () => aborted);
      }
      // スキップした失敗 entry が残っている場合は playlist 追加を保留して終了する (#948)。
      // 失敗分のみ再実行して完走した run が playlist 追加を実行する（同名 playlist の重複作成と
      // 歯抜け playlist を防ぐ）。failedIndex=total で persist し、failedIndices を再実行導線へ渡す。
      if (failedIndices.length > 0) {
        persistInterruptState(total);
        const list = failedIndices.map((i) => i + 1).join(", ");
        emitProgress({
          phase: PHASE.FINISHED,
          total,
          message: `${failedIndices.length} 件の entry が失敗しました (entry ${list})。「失敗分のみ再実行」で完走後に playlist 追加が実行されます。`,
        });
        return;
      }
      let verifiedPlaylistClipCount = expectedPlaylistClipCount;
      if (aborted) {
        persistInterruptState(total);
        emitProgress({ phase: PHASE.STOPPED, total });
        return;
      }
      try {
        await waitForSubmittedClipsComplete(expectedPlaylistClipCount, previousSubmittedClipIds, () => aborted);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        persistInterruptState(total);
        emitProgress({ phase: PHASE.ERROR, index: total, total, message });
        return;
      }
      if (aborted) {
        persistInterruptState(total);
        emitProgress({ phase: PHASE.STOPPED, total });
        return;
      }
      try {
        verifiedPlaylistClipCount = await addClipsToPlaylist(
          total,
          playlistName,
          previousSubmittedClipIds,
          expectedPlaylistClipCount,
          entries,
          order,
        );
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        persistInterruptState(total);
        emitProgress({ phase: PHASE.ERROR, index: total, total, message });
        return;
      }
      if (aborted) {
        persistInterruptState(total);
        emitProgress({ phase: PHASE.STOPPED, total });
        return;
      }

      // --- DOWNLOADING phase (#1146) ---
      const fullCollectionClipCount = total * CLIPS_PER_REQUEST;
      if (expectedPlaylistClipCount >= fullCollectionClipCount) {
        persistInterruptState(total);
        try {
          const downloadContext = await resolveDownloadContext();
          const downloadError = await downloadFlow.downloadBestEffort(
            downloadContext,
            collectionId,
            total,
            verifiedPlaylistClipCount,
          );
          keepResumeStateForDownloadRetry = downloadError !== null;
          if (downloadError !== null) {
            emitProgress({ phase: PHASE.ERROR, index: total, total, message: downloadError });
            return;
          }
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          keepResumeStateForDownloadRetry = true;
          emitProgress({ phase: PHASE.ERROR, index: total, total, message });
          return;
        }
      }
      if (aborted) {
        persistInterruptState(total);
        emitProgress({ phase: PHASE.STOPPED, total });
        return;
      }
      // 全 entry 完了。この collection の resume state を消去する (#872 要件5)。
      // リロード前に消去完了を await する (#1411 要件3): 逆順だとリロード後の
      // ResumeBanner が「中断からの再開」と誤判定する。消去に失敗しても FINISHED は
      // 維持し（void 時代からの不変条件: 終端 phase を必ず出す）、誤判定を避けるため
      // リロードのみ見送る。残る stale selection は次 run の Cmd+P 前ガードが検知する。
      let resumeStateCleared = true;
      if (!keepResumeStateForDownloadRetry) {
        try {
          await clearResumeStateForCollection(collectionId);
        } catch (err) {
          resumeStateCleared = false;
          console.warn("[suno-helper] resume state の消去に失敗しました。完了時リロードを見送ります:", err);
        }
      }
      emitProgress({ phase: PHASE.FINISHED, total });
      // run 一式完了時リロード (#1411 要件2)。playlist 追加で作った multi-select 状態は
      // Suno 内部 state に残り、同一タブの次 run の Cmd+P に混入するためページごと破棄する。
      // collection mode の run は playlist phase を実行するため対象。
      // リロード前に FINISHED snapshot を退避し、popup 再 open 時の完了結果表示を引き継ぐ。
      if (playlistName && resumeStateCleared && (await persistFinishedSnapshotForReload())) {
        scheduleRunCompleteReload();
      }
    }

    onMessage("run", ({ data }) => {
      // 二重実行ガード (#892 要件7)。実行中の run 再着信は no-op で ack のみ返す（再開連打対策）。
      if (running) {
        return { ok: true } as const;
      }
      const {
        entries,
        playlistName,
        durationFilter,
        range,
        collectionId,
        indices,
        submittedClipIds,
        playlistExpectedClipCount,
      } = assertRunPayload(data);
      // 直前 run の完了時リロードが保留中なら取り消す (#1411)。猶予中に受理した新 run を
      // リロードが巻き添えに殺すと STOPPED/ERROR も resume state も残らない。取り消しで
      // 残る stale selection は Cmd+P 前ガードが検知する。
      cancelScheduledRunCompleteReload();
      currentSnapshot = initSnapshot(entries, { collectionId, playlistName });
      // 新 run 開始で直近完了 run の退避 snapshot を消去する（前 run の完了表示が復元されるのを防ぐ）。
      // in-memory の currentSnapshot が queryProgress で優先されるため fire-and-forget でよい。
      void clearFinishedSnapshot();
      if (detectSunoViewMode() === "unknown") {
        emitProgress({
          phase: PHASE.ERROR,
          total: entries.length,
          message:
            "Suno の表示ビューを検出できません。List / Waveform / Grid のいずれかに切り替えてから再実行してください。",
        });
        return { ok: true } as const;
      }
      running = true;
      aborted = false;
      lastSubmittedEntryIndex = -1;
      tracker.clearSubmittedIds();
      // run 中のみ active feed poll で clip status を追う (#948)。passive 観測が生きていれば
      // poller は stale 判定で自発的に黙る（intervalMs ごとの no-op tick のみ）。
      feedPoller.start();
      void runAll(entries, {
        durationFilter,
        range,
        collectionId,
        playlistName,
        indices,
        submittedClipIds,
        playlistExpectedClipCount,
      }).finally(() => {
        running = false;
        feedPoller.stop();
      });
      return { ok: true } as const;
    });

    onMessage("stop", () => {
      aborted = true;
      return { ok: true } as const;
    });

    onMessage("retryPlaylist", ({ data }) => {
      if (running) {
        return { ok: true } as const;
      }
      const { playlistName, submittedClipIds, expectedClipCount, collectionId, shouldDownload } =
        assertRetryPlaylistPayload(data);
      currentSnapshot = initSnapshot([], { collectionId, playlistName });
      // 新しい実行の開始なので直近完了 run の退避 snapshot を消去する（run handler と同じ）。
      void clearFinishedSnapshot();
      // 直前 run の完了時リロードが保留中なら取り消す (#1411)。理由は run handler と同じ。
      cancelScheduledRunCompleteReload();
      running = true;
      aborted = false;
      void (async () => {
        try {
          const verifiedClipCount = await addClipsToPlaylist(
            0,
            playlistName,
            submittedClipIds,
            expectedClipCount,
            [],
            [],
          );
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, total: 0 });
            return;
          }
          if (shouldDownload) {
            const downloadContext = await resolveDownloadContext();
            await downloadFlow.performDownload(downloadContext, collectionId, verifiedClipCount, verifiedClipCount);
          }
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, total: 0 });
            return;
          }
          // 消去 → FINISHED → リロードの順序保証は runAll の完了経路と同じ (#1411 要件3)。
          // 消去失敗はここまでの成功（playlist 追加 + download）を ERROR に変えない:
          // catch へ流すと再試行を誘い、同名 playlist の重複作成につながるため、
          // FINISHED を維持してリロードのみ見送る。
          let resumeStateCleared = true;
          try {
            await clearResumeStateForCollection(collectionId);
          } catch (err) {
            resumeStateCleared = false;
            console.warn("[suno-helper] resume state の消去に失敗しました。完了時リロードを見送ります:", err);
          }
          emitProgress({ phase: PHASE.FINISHED, total: 0 });
          // retryPlaylist も playlist 追加で multi-select 状態を作るため完了時にページごと破棄する (#1411)。
          // リロード前に FINISHED snapshot を退避する（runAll の完了経路と同じ）。
          if (resumeStateCleared && (await persistFinishedSnapshotForReload())) {
            scheduleRunCompleteReload();
          }
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          emitProgress({ phase: PHASE.ERROR, total: 0, message });
        }
      })().finally(() => {
        running = false;
      });
      return { ok: true } as const;
    });

    onMessage("retryDownload", ({ data }) => {
      if (running) {
        return { ok: true } as const;
      }
      const { collectionId, submittedClipIds, expectedClipCount } = assertRetryDownloadPayload(data);
      currentSnapshot = initSnapshot([], { collectionId });
      // 新しい実行の開始なので直近完了 run の退避 snapshot を消去する（run handler と同じ）。
      void clearFinishedSnapshot();
      // 直前 run の完了時リロードが保留中なら取り消す (#1411)。理由は run handler と同じ。
      cancelScheduledRunCompleteReload();
      running = true;
      aborted = false;
      void (async () => {
        try {
          const downloadContext = await resolveDownloadContext();
          const result = await downloadFlow.retryDownload({
            context: downloadContext,
            collectionId,
            submittedClipIds,
            expectedClipCount,
            selectClipIds: async (clipIds) => {
              await scrollAndMultiSelectByIds(clipIds, { isAborted: () => aborted });
            },
            clearResumeState: clearResumeStateForCollection,
          });
          // retryDownload も selectClipIds で multi-select 状態を作るため、完了時に
          // ページごと破棄する (#1411)。この経路だけリロードが無いと、次 run が
          // 確実に Cmd+P 前ガードで止まり手動リロードを強いられる。
          // リロード前に FINISHED snapshot を退避する（runAll の完了経路と同じ）。
          if (result.completedAndCleared && (await persistFinishedSnapshotForReload())) {
            scheduleRunCompleteReload();
          }
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          emitProgress({ phase: PHASE.ERROR, total: 0, message });
        }
      })().finally(() => {
        running = false;
      });
      return { ok: true } as const;
    });

    onMessage("adoptSelectedClips", ({ data }) => {
      if (running) {
        throw new Error("実行中は選択中 clip を採用できません。停止または完了後に再実行してください。");
      }
      return readSelectedClipIds({
        isAborted: () => aborted,
        expectedClipCount: data.expectedClipCount,
      }).then((clipIds) => ({ ok: true as const, clipIds }));
    });

    // popup 再 open 時の進捗復元 (#852)。in-memory snapshot が SSOT。完了時リロード (#1411) で
    // in-memory が破棄された後は、リロード直前に退避した直近完了 run の snapshot を fallback で返す
    // （stale 判定込み、次 run 開始で消去）。どちらも無ければ null（buildRestoreState が従来表示へ）。
    onMessage("queryProgress", async () => currentSnapshot ?? (await readFreshFinishedSnapshot(Date.now())));
  },
});
