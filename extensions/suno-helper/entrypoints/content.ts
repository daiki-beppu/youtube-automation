// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行 (content script)。
// DOM 操作は shared/dom の純関数へ委譲し、本ファイルは連続実行のフロー制御に専念する。
import type { PromptEntry } from "../../shared/api";
import {
  CLIPS_PER_REQUEST,
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
  resolveInterruptIndex,
  type RunRange,
  writeResumeState,
} from "../lib/resume-state";
import { InjectNotAcknowledgedError, injectWithVerification } from "../lib/inject-retry";
import { createAckWaiter, markAck } from "../lib/ack-probe";
import { attachBridgeListener, createFeedPoller } from "../lib/bridge-listener";
import { createClipTracker } from "../lib/clip-tracker";
import {
  abortableSleep,
  CAPTCHA_WAIT_TIMEOUT_MS,
  GENERATE_TIMEOUT_MS,
  POLL_INTERVAL_MS,
  SETTLE_MS,
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
  ensureClipRowsLoaded,
  fillPlaylistNameAndCreate,
  multiSelectClips,
  openAddToPlaylistDialogViaCmdP,
  waitForPlaylistDialogClose,
} from "../../shared/playlist-dom";
import { scrapePlaylistsFromMe } from "../../shared/playlist-scrape";
import { triggerPlaylistCaptureFailSoft } from "../lib/auto-capture";
import { onMessage, sendMessage } from "../lib/messaging";

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
        throw new Error("Lyrics 欄が見つかりません。Instrumental OFF（Custom Mode）になっているか確認してください。");
      }
      if (title) {
        // Song Title は entry.title 優先、無ければ entry.name で代替する (#844)。
        setNativeValue(title, entry.title ?? entry.name);
      } else {
        // title 欄不在は Suno 側 UI 改装の可能性。style/lyrics と違い fail-soft（警告のみで続行）。
        console.warn("Song Title 欄が見つかりませんでした。タイトル注入を skip して続行します。");
      }
      // Custom Mode > More Options の 3 フィールド (#900)。radix slider への注入は keydown dispatch
      // (ArrowRight/Left, bubbles:true composed:true) を採用した。実機検証で radix Slider root の
      // keydown listener に合成イベントが届き aria-valuenow が動くことを確認済み（pointer event 合成
      // fallback は不要だった）。entry に値があり selector が不在なら injectAdvancedFields が throw する
      // (fail-loud)。値が無ければ skip する (fail-soft、後方互換)。
      await injectAdvancedFields(entry, resolveAdvancedFields());
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
    async function addClipsToPlaylist(entryCount: number, playlistName: string): Promise<void> {
      emitProgress({ phase: PHASE.ADDING_TO_PLAYLIST, total: entryCount, message: playlistName });
      // 直近 entry 数 × CLIPS_PER_REQUEST 件の clip を multi-select する。
      // clip list は遅延ロード（無限スクロール）のため、初期ロード（40 件）では不足する場合がある (#924)。
      // ensureClipRowsLoaded がスクロールで追加ロードを促し、count 件揃うまで待機する。
      // clip row が 1 件も無ければ fail-loud throw する（#881）。
      const rows = await ensureClipRowsLoaded(entryCount * CLIPS_PER_REQUEST, {
        isAborted: () => aborted,
      });
      if (aborted) {
        return; // ロード待ち中に停止された。部分状態のまま Cmd+P に進まない（呼び出し元の STOPPED guard が persist する）
      }
      await multiSelectClips(rows);
      await abortableSleep(SETTLE_MS, () => aborted);

      const dialog = await openAddToPlaylistDialogViaCmdP();
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
    }

    interface RunOptions {
      // 0-based inclusive な実行範囲 (#872)。未指定は全 entry。判断A: range 指定でも entries 全体と
      // 絶対 index を保ち、range 内の entry だけを処理する（slice 再採番による index ズレを起こさない）。
      range?: RunRange;
      // ERROR 停止時に resume state を紐付ける collection 識別子 (#872)。単一ファイル mode は undefined。
      collectionId?: string;
      // collection mode のときの playlist 名 (#854)。全 entry 完了後の clip 一括追加に使う。
      playlistName?: string;
    }

    async function runAll(entries: PromptEntry[], options: RunOptions): Promise<void> {
      const { range, collectionId, playlistName } = options;
      // 速度プリセット (#875) を run 開始時に確定する。以降のペーシング（間隔/並列数/retry/ack）は
      // 既存定数の代わりにこの preset 値を使う。未選択でも storage fallback で Balanced になる。
      const preset = resolveSpeedPreset(await readSpeedPresetId());
      // Suno 同時生成キューに積める clip 数の上限（preset の並列リクエスト数 × 2 clip）。
      const maxGeneratingClips = preset.maxInflightRequests * CLIPS_PER_REQUEST;
      const total = entries.length;
      const startIndex = range ? range.start : 0;
      const endIndex = range ? range.end : total - 1;
      // 中断 entry を永続化し、reload 後の ResumeBanner で続きから再開できるようにする。
      // ERROR phase (#872 要件3) と STOPPED phase (#898 要件1/2/3) の共通処理。failedIndex 名は
      // そのまま流用し (要件3)、中断 index を載せる。collectionId が無い単一ファイル mode は
      // 再開対象を特定できないため永続化しない（両 phase 共通の guard、要件4 と一貫）。
      function persistInterruptState(interruptedIndex: number): void {
        if (collectionId) {
          void writeResumeState({ collectionId, failedIndex: interruptedIndex, total, timestamp: Date.now() });
        }
      }
      for (let i = startIndex; i <= endIndex; i++) {
        if (aborted) {
          // ループ先頭の中断: この時点でまだ Generate を click していないため i をそのまま使う (#924)。
          persistInterruptState(i);
          emitProgress({ phase: PHASE.STOPPED, index: i, total });
          return;
        }
        try {
          // Suno のキュー上限（20 clip）を超えると後続が silent fail するため、投入前に空きを待つ。
          emitProgress({ phase: PHASE.WAITING_SLOT, index: i, total });
          await waitForQueueSlot(maxGeneratingClips, {
            isAborted: () => aborted,
            pollIntervalMs: POLL_INTERVAL_MS,
            // queue 空き待ちは single clip 完了待ち (GENERATE_TIMEOUT_MS) とは別系統の 5 分 (#864 root cause 1)。
            timeoutMs: QUEUE_SLOT_WAIT_TIMEOUT_MS,
            queueErrorWaitMs: QUEUE_ERROR_WAIT_MS,
            // bridge の status ベースカウント (#948)。Remix disabled プロキシは完了後も disabled が
            // 残り過大カウントするため、観測があれば一次情報（API status）で数える。
            getCount: currentInFlightCount,
          });
          if (aborted) {
            // waitForQueueSlot 後の中断: まだ Generate を click していないため i をそのまま使う (#924)。
            persistInterruptState(i);
            emitProgress({ phase: PHASE.STOPPED, index: i, total });
            return;
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
          if (aborted) {
            // injectWithVerification 完了後の中断チェック。injectAndGenerate 内で Generate を click し
            // waitForGeneration まで完了しているため submitted=true。interruptIndex は i+1 とし、
            // 再開時にこの entry を重複生成しない (#924)。
            // emitProgress の index も interruptIndex にする: snapshot.applyProgress (lib/snapshot.ts:47) が
            // ERROR payload の index を failedIndex として記録し、useSunoRunner.ts:140-142 が chrome.storage
            // 喪失時の冗長ソースに使うため、両系統の failedIndex を一致させる必要がある。
            const interruptIndex = resolveInterruptIndex(i, lastSubmittedEntryIndex === i, false);
            persistInterruptState(interruptIndex);
            emitProgress({ phase: PHASE.STOPPED, index: interruptIndex, total });
            return;
          }
          emitProgress({ phase: PHASE.DONE, index: i, total });
          // Create→clip-row DOM 反映ラグによる過剰投入 (race) を避けるため、次の投入前に間隔を空ける (#847)。
          // preset の基準間隔に ±jitter を加えて bot 判定の固定間隔シグナルを消す (#875)。毎回 fresh 算出する。
          await abortableSleep(applyJitter(preset.interCreateDelayMs, preset.jitterMs), () => aborted);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          // interruptIndex: submitted（Generate click 済み）かつ silent drop 確定でない → i+1（重複しない）。
          // InjectNotAcknowledgedError（全 attempt 未受理）は silent drop 確定のため i（再生成する）。
          // emitProgress の index も interruptIndex にする: snapshot.applyProgress (lib/snapshot.ts:47) が
          // ERROR payload の index を failedIndex として記録し、useSunoRunner.ts:140-142 が chrome.storage
          // 喪失時の冗長ソースに使うため、両系統の failedIndex を一致させる必要がある (#924)。
          const interruptIndex = resolveInterruptIndex(
            i,
            lastSubmittedEntryIndex === i,
            err instanceof InjectNotAcknowledgedError,
          );
          emitProgress({ phase: PHASE.ERROR, index: interruptIndex, total, message });
          // 失敗 index を永続化し、次回 popup 起動時の再開バナーで提示する (#872 要件3)。
          persistInterruptState(interruptIndex);
          return;
        }
      }
      // collection mode のみ: 全 entry 生成後、FINISHED 直前に clip 一括 playlist 追加を実行する (#854)。
      if (playlistName) {
        if (aborted) {
          persistInterruptState(total);
          emitProgress({ phase: PHASE.STOPPED, total });
          return;
        }
        try {
          await addClipsToPlaylist(total, playlistName);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          emitProgress({ phase: PHASE.ERROR, total, message });
          return;
        }
        if (aborted) {
          persistInterruptState(total);
          emitProgress({ phase: PHASE.STOPPED, total });
          return;
        }
        // playlist 化完了直後、FINISHED 直前に capture を自動 trigger する (#893 追加要件 A)。
        // bg tab で `/me` を開閉し scrape→POST する実処理は background が担う。fail soft:
        // 送信失敗は warning のみで FINISHED へ進める（capture はベストエフォート）。
        await triggerPlaylistCaptureFailSoft(
          () => sendMessage("requestPlaylistCapture", undefined),
          (err) => console.warn("[suno-helper] playlist capture trigger failed:", err),
        );
      }
      // 全 entry 完了。この collection の resume state を消去する (#872 要件5)。
      if (collectionId) {
        void clearResumeStateForCollection(collectionId);
      }
      emitProgress({ phase: PHASE.FINISHED, total });
    }

    onMessage("run", ({ data }) => {
      // 二重実行ガード (#892 要件7)。実行中の run 再着信は no-op で ack のみ返す（再開連打対策）。
      if (running) {
        return { ok: true } as const;
      }
      running = true;
      aborted = false;
      lastSubmittedEntryIndex = -1;
      // 後方互換: 旧形式の配列 payload は { entries } に wrap する (#854)。range / collectionId は無し。
      const { entries, playlistName, range, collectionId } = Array.isArray(data)
        ? { entries: data, playlistName: undefined, range: undefined, collectionId: undefined }
        : data;
      currentSnapshot = initSnapshot(entries, playlistName);
      // run 中のみ active feed poll で clip status を追う (#948)。passive 観測が生きていれば
      // poller は stale 判定で自発的に黙る（intervalMs ごとの no-op tick のみ）。
      feedPoller.start();
      void runAll(entries, { range, collectionId, playlistName }).finally(() => {
        running = false;
        feedPoller.stop();
      });
      return { ok: true } as const;
    });

    onMessage("stop", () => {
      aborted = true;
      return { ok: true } as const;
    });

    // popup 再 open 時の進捗復元 (#852)。run 未実行は null（buildRestoreState が従来表示へフォールバック）。
    onMessage("queryProgress", () => currentSnapshot);

    // 自身の document（Suno `/me`）から playlist 一覧を scrape して返す (#893)。
    // overlay の手動 Capture（background 経由）と background の bg tab 自動 capture が共用する。
    onMessage("capturePlaylists", () => scrapePlaylistsFromMe(document));
  },
});
