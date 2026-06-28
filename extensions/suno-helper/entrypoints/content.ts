// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行 (content script)。
// DOM 操作は shared/dom の純関数へ委譲し、本ファイルは連続実行のフロー制御に専念する。
import type { PromptEntry } from "../../shared/api";
import {
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
import { applyJitter, readSpeedPresetId, resolveSpeedPreset } from "../lib/preset-state";
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
import { triggerDownloadAll } from "../lib/download";
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
import { scrapePlaylistsFromMe } from "../../shared/playlist-scrape";
import { onMessage, sendMessage } from "../lib/messaging";
import { downloadFormatItem, serverUrlItem } from "../lib/storage";

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

    // --- Download all 完了待ち (#1146) ---
    // background から downloadComplete メッセージを受信するための resolver。
    // startDownload → triggerDownloadAll → waitForDownloadComplete の流れで使う。
    type DownloadResult = { ok: true; filename: string } | { ok: false; message: string };

    let downloadCompleteResolver: ((value: DownloadResult | null) => void) | null = null;

    /** background からの downloadComplete メッセージを待つ。タイムアウトまたは abort で null を返す。 */
    function waitForDownloadComplete(isAborted: () => boolean): Promise<DownloadResult | null> {
      const DOWNLOAD_COMPLETE_TIMEOUT_MS = 660000; // background watcher の fallback を待つため 11 分
      return new Promise((resolve) => {
        downloadCompleteResolver = resolve;
        const deadline = Date.now() + DOWNLOAD_COMPLETE_TIMEOUT_MS;
        const tick = (): void => {
          if (downloadCompleteResolver === null) {
            // 既に resolve 済み（downloadComplete メッセージ受信済み）
            return;
          }
          if (isAborted() || Date.now() >= deadline) {
            downloadCompleteResolver = null;
            resolve(null);
            return;
          }
          setTimeout(tick, 1000);
        };
        tick();
      });
    }

    // background → content: ダウンロード完了通知の受信ハンドラ (#1146)。
    onMessage("downloadComplete", ({ data }) => {
      if (downloadCompleteResolver) {
        const resolver = downloadCompleteResolver;
        downloadCompleteResolver = null;
        resolver({ ok: true, filename: data.filename });
      }
    });

    onMessage("downloadFailed", ({ data }) => {
      if (downloadCompleteResolver) {
        const resolver = downloadCompleteResolver;
        downloadCompleteResolver = null;
        resolver({ ok: false, message: data.message });
      }
    });

    async function resolvePlaylistUrl(playlistName: string): Promise<string> {
      const item = scrapePlaylistsFromMe(globalThis.document as Document).find(
        (playlist) => playlist.title === playlistName,
      );
      if (item) {
        return item.url;
      }
      const resolved = await sendMessage("resolvePlaylistUrl", { playlistName });
      return resolved.url;
    }

    /**
     * Download all の低レベル副作用本体 (#1146/#1217)。
     * 1. DOWNLOADING phase に遷移し DOM で Download all を起動
     * 2. chrome.downloads 完了を待ち file_count:N で postDownloaded
     */
    async function performDownload(
      collectionId: string,
      progressTotal: number,
      expectedFileCount: number,
      sunoPlaylistUrl: string,
      isAborted: () => boolean,
    ): Promise<void> {
      const format = await downloadFormatItem.getValue();
      const baseUrl = (await serverUrlItem.getValue()).trim();

      if (isAborted()) return;

      emitProgress({ phase: PHASE.DOWNLOADING, total: progressTotal, message: `${format.toUpperCase()} 形式` });
      const startResult = await sendMessage("startDownload", { format });
      if (!startResult?.ok) {
        throw new Error(startResult?.message ?? "Download all 監視を開始できませんでした");
      }
      const downloadPromise = waitForDownloadComplete(isAborted);
      let watcherActive = true;
      try {
        await triggerDownloadAll(format);

        const downloadResult = await downloadPromise;

        if (isAborted()) return;

        if (!downloadResult) {
          throw new Error("Download all がタイムアウトしました");
        }
        watcherActive = false;
        if (!downloadResult.ok) {
          throw new Error(downloadResult.message);
        }

        await sendMessage("postDownloaded", {
          baseUrl,
          collectionId,
          body: {
            file_count: expectedFileCount,
            expected_file_count: expectedFileCount,
            format,
            suno_playlist_url: sunoPlaylistUrl,
            download_path: downloadResult.filename,
          },
        });
      } finally {
        if (watcherActive) {
          downloadCompleteResolver = null;
          await sendMessage("cancelDownload", undefined).catch((cancelErr: unknown) => {
            console.warn("[suno-helper] cancelDownload 中継失敗:", cancelErr);
          });
        }
      }
    }

    async function recordPlaylistUrl(collectionId: string, sunoPlaylistUrl: string): Promise<void> {
      const format = await downloadFormatItem.getValue();
      const baseUrl = (await serverUrlItem.getValue()).trim();
      await sendMessage("postDownloaded", {
        baseUrl,
        collectionId,
        body: {
          file_count: 0,
          format,
          suno_playlist_url: sunoPlaylistUrl,
        },
      });
    }

    async function downloadBestEffort(
      collectionId: string,
      progressTotal: number,
      expectedFileCount: number,
      sunoPlaylistUrl: string,
      isAborted: () => boolean,
    ): Promise<string | null> {
      try {
        await performDownload(collectionId, progressTotal, expectedFileCount, sunoPlaylistUrl, isAborted);
        return null;
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        console.warn(`[suno-helper] Download all failed: ${message}`);
        emitProgress({
          phase: PHASE.DOWNLOADING,
          total: progressTotal,
          message: `ダウンロード失敗（手動でダウンロードしてください）: ${message}`,
        });
        return message;
      }
    }

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
        setNativeValue(lyrics, entry.lyrics);
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
      const allSubmittedIds = [...previousSubmittedClipIds, ...tracker.getSubmittedIds()];
      const observedCount = new Set(allSubmittedIds).size;
      if (observedCount !== expectedClipCount) {
        console.warn(
          `[suno-helper] bridge observation gap: expected ${expectedClipCount} clip IDs, observed ${observedCount}`,
        );
      }
      const submittedIds = resolvePlaylistClipIds(
        previousSubmittedClipIds,
        tracker.getSubmittedIds(),
        expectedClipCount,
      );
      const titleFallbackMap = buildTitleFallbackMap(entries, order, submittedIds);
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
      // 0-based inclusive な実行範囲 (#872)。未指定は全 entry。判断A: range 指定でも entries 全体と
      // 絶対 index を保ち、range 内の entry だけを処理する（slice 再採番による index ズレを起こさない）。
      range?: RunRange;
      // ERROR 停止時に resume state を紐付ける collection 識別子 (#872)。単一ファイル mode は undefined。
      collectionId?: string;
      // collection mode のときの playlist 名 (#854)。全 entry 完了後の clip 一括追加に使う。
      playlistName?: string;
      // 実行対象の 0-based index 列 (#948)。「失敗分のみ再実行」で使う。指定時は range より優先。
      indices?: number[];
      // 再開前の run で観測済みの playlist 対象 clip ID。
      submittedClipIds?: string[];
      // playlist 追加時に揃っているべき clip ID 件数。
      playlistExpectedClipCount?: number;
    }

    async function runAll(entries: PromptEntry[], options: RunOptions): Promise<void> {
      const { range, collectionId, playlistName, submittedClipIds, playlistExpectedClipCount } = options;
      const previousSubmittedClipIds = submittedClipIds ?? [];
      // 速度プリセット (#875) を run 開始時に確定する。以降のペーシング（間隔/並列数/retry/ack）は
      // 既存定数の代わりにこの preset 値を使う。未選択でも storage fallback で Balanced になる。
      const preset = resolveSpeedPreset(await readSpeedPresetId());
      // Suno 同時生成キューに積める clip 数の上限（preset の並列リクエスト数 × 2 clip）。
      const maxGeneratingClips = preset.maxInflightRequests * CLIPS_PER_REQUEST;
      const total = entries.length;
      const startIndex = range ? range.start : 0;
      const endIndex = range ? range.end : total - 1;
      // 実行対象の 0-based index 列 (#948)。indices（失敗分のみ再実行）が最優先、無ければ range 由来。
      const order = options.indices ?? Array.from({ length: endIndex - startIndex + 1 }, (_, k) => startIndex + k);
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
      // そのまま流用し (要件3)、中断 index を載せる。collectionId が無い単一ファイル mode は
      // 再開対象を特定できないため永続化しない（両 phase 共通の guard、要件4 と一貫）。
      // スキップ済み failedIndices があれば一緒に永続化する (#948)。
      function persistInterruptState(interruptedIndex: number): void {
        if (collectionId) {
          const persistedSubmittedClipIds = Array.from(
            new Set([...previousSubmittedClipIds, ...tracker.getSubmittedIds()]),
          );
          currentSnapshot =
            currentSnapshot === null
              ? currentSnapshot
              : {
                  ...currentSnapshot,
                  failedIndex: interruptedIndex,
                  submittedClipIds: persistedSubmittedClipIds,
                  playlistExpectedClipCount: expectedPlaylistClipCount,
                };
          void writeResumeState({
            collectionId,
            failedIndex: interruptedIndex,
            total,
            timestamp: Date.now(),
            failedIndices: failedIndices.length > 0 ? [...failedIndices] : undefined,
            submittedClipIds: persistedSubmittedClipIds,
            playlistExpectedClipCount: expectedPlaylistClipCount,
          });
        }
      }
      for (const i of order) {
        if (aborted) {
          // ループ先頭の中断: この時点でまだ Generate を click していないため i をそのまま使う (#924)。
          persistInterruptState(i);
          emitProgress({ phase: PHASE.STOPPED, index: i, total });
          return;
        }
        // 1 entry の実行を失敗分類つきで包む (#948)。一時的な失敗は preset.maxEntryRetry 回まで
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
              maxRetry: preset.maxInjectRetry,
              ackTimeoutMs: preset.injectAckTimeoutMs,
              pollIntervalMs: POLL_INTERVAL_MS,
              describeEntry: () => `entry ${i} (${entries[i].title ?? entries[i].name})`,
            });
          },
          isAborted: () => aborted,
          // Generate click 済みで受理失敗確定でないエラー（典型: 生成完了待ち timeout）は再実行すると
          // 重複生成になるため presumed-done（resolveInterruptIndex の i+1 判断と同じ）。
          wasSubmitted: (err) => lastSubmittedEntryIndex === i && !(err instanceof InjectNotAcknowledgedError),
          isFatal: (err) => err instanceof FatalRunError,
          maxRetry: preset.maxEntryRetry,
          retryDelayMs: () => applyJitter(preset.interCreateDelayMs, preset.jitterMs),
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
          persistInterruptState(interruptIndex);
          return;
        }
        if (result.outcome === "aborted" || aborted) {
          // attempt 中の中断（waitForQueueSlot / injectAndGenerate 内の silent return 含む）。
          // Generate click 済みなら i+1 を persist し再開時の重複生成を防ぐ (#924)。
          const interruptIndex = resolveInterruptIndex(i, lastSubmittedEntryIndex === i, false);
          persistInterruptState(interruptIndex);
          emitProgress({ phase: PHASE.STOPPED, index: interruptIndex, total });
          return;
        }
        if (result.outcome === "failed") {
          const message = result.error instanceof Error ? result.error.message : String(result.error);
          failedIndices.push(i);
          console.warn(`[suno-helper] entry ${i} をスキップして続行します: ${message}`);
          emitProgress({ phase: PHASE.ENTRY_FAILED, index: i, total, message });
          continue; // run 全体は止めない。retry 間で既に間隔を空けているため即次 entry へ。
        }
        if (result.outcome === "presumed-done") {
          const message = result.error instanceof Error ? result.error.message : String(result.error);
          console.warn(`[suno-helper] entry ${i} は投入済みのため生成済み扱いで続行します: ${message}`);
        }
        emitProgress({ phase: PHASE.DONE, index: i, total });
        // Create→clip-row DOM 反映ラグによる過剰投入 (race) を避けるため、次の投入前に間隔を空ける (#847)。
        // preset の基準間隔に ±jitter を加えて bot 判定の固定間隔シグナルを消す (#875)。毎回 fresh 算出する。
        await abortableSleep(applyJitter(preset.interCreateDelayMs, preset.jitterMs), () => aborted);
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
      // collection mode のみ: 全 entry 生成後、FINISHED 直前に clip 一括 playlist 追加を実行する (#854)。
      if (playlistName) {
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
        if (collectionId && !aborted) {
          const fullCollectionClipCount = total * CLIPS_PER_REQUEST;
          if (expectedPlaylistClipCount >= fullCollectionClipCount) {
            persistInterruptState(total);
            try {
              const sunoPlaylistUrl = await resolvePlaylistUrl(playlistName);
              await recordPlaylistUrl(collectionId, sunoPlaylistUrl);
              const downloadError = await downloadBestEffort(
                collectionId,
                total,
                verifiedPlaylistClipCount,
                sunoPlaylistUrl,
                () => aborted,
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
        }
      }
      // 全 entry 完了。この collection の resume state を消去する (#872 要件5)。
      if (collectionId && !keepResumeStateForDownloadRetry) {
        void clearResumeStateForCollection(collectionId);
      }
      emitProgress({ phase: PHASE.FINISHED, total });
    }

    onMessage("run", ({ data }) => {
      // 二重実行ガード (#892 要件7)。実行中の run 再着信は no-op で ack のみ返す（再開連打対策）。
      if (running) {
        return { ok: true } as const;
      }
      // 後方互換: 旧形式の配列 payload は { entries } に wrap する (#854)。range / collectionId は無し。
      const { entries, playlistName, range, collectionId, indices, submittedClipIds, playlistExpectedClipCount } =
        Array.isArray(data)
          ? {
              entries: data,
              playlistName: undefined,
              range: undefined,
              collectionId: undefined,
              indices: undefined,
              submittedClipIds: undefined,
              playlistExpectedClipCount: undefined,
            }
          : data;
      currentSnapshot = initSnapshot(entries, playlistName);
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
      const { playlistName, submittedClipIds, expectedClipCount, collectionId, shouldDownload } = data;
      currentSnapshot = initSnapshot([], playlistName);
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
          if (collectionId && shouldDownload) {
            const sunoPlaylistUrl = await resolvePlaylistUrl(playlistName);
            await recordPlaylistUrl(collectionId, sunoPlaylistUrl);
            await performDownload(collectionId, verifiedClipCount, verifiedClipCount, sunoPlaylistUrl, () => aborted);
          }
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, total: 0 });
            return;
          }
          if (collectionId) {
            void clearResumeStateForCollection(collectionId);
          }
          emitProgress({ phase: PHASE.FINISHED, total: 0 });
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
      const { collectionId, playlistName, submittedClipIds, expectedClipCount } = data;
      currentSnapshot = initSnapshot([], undefined);
      running = true;
      aborted = false;
      void (async () => {
        try {
          const total = submittedClipIds.length;
          if (submittedClipIds.length === 0) {
            throw new Error("retryDownload に必要な clip ID がありません");
          }
          emitProgress({ phase: PHASE.ADDING_TO_PLAYLIST, total, message: "clip を選択中…" });
          await scrollAndMultiSelectByIds(submittedClipIds, { isAborted: () => aborted });
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, total: 0 });
            return;
          }
          const sunoPlaylistUrl = await resolvePlaylistUrl(playlistName);
          await performDownload(collectionId, total, expectedClipCount ?? total, sunoPlaylistUrl, () => aborted);
          if (aborted) {
            emitProgress({ phase: PHASE.STOPPED, total: 0 });
            return;
          }
          if (collectionId) {
            void clearResumeStateForCollection(collectionId);
          }
          emitProgress({ phase: PHASE.FINISHED, total: 0 });
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

    // popup 再 open 時の進捗復元 (#852)。run 未実行は null（buildRestoreState が従来表示へフォールバック）。
    onMessage("queryProgress", () => currentSnapshot);

    // 自身の document（Suno `/me`）から playlist 一覧を scrape して返す (#893)。
    // overlay の手動 Capture（background 経由）と background の bg tab 自動 capture が共用する。
    onMessage("capturePlaylists", () => scrapePlaylistsFromMe(document));
  },
});
