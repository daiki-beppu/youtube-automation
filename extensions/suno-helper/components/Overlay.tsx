import type { OverlayState } from "@youtube-automation/extensions-shared/overlay-state";
import { OverlayShell } from "@youtube-automation/ui";
import { useCallback, useEffect, useState } from "react";

import {
  type ChallengeLogRecord,
  readChallengeLog,
} from "../lib/challenge-log";
import { onMessage, sendMessage } from "../lib/messaging";
import { SUNO_OVERLAY_BRAND } from "../lib/overlay-brand";
import { readOverlayState, writeOverlayState } from "../lib/overlay-storage";
import { App } from "./App";
import { ReloadRequiredNotice } from "./ReloadRequiredNotice";

const RECENT_CHALLENGE_RECORD_COUNT = 5;
type ChallengeLogCopyResult = "idle" | "success" | "failure";

function allowlistedChallengeRecord(
  record: ChallengeLogRecord
): ChallengeLogRecord {
  return {
    timestamp: record.timestamp,
    source: record.source,
    runMode: record.runMode,
    unattended: record.unattended,
    entryIndex: record.entryIndex,
    total: record.total,
    challengeLevel: record.challengeLevel,
    recentCreateCount: record.recentCreateCount,
    runCreateCount: record.runCreateCount,
    lastCreateIntervalMs: record.lastCreateIntervalMs,
    appliedDelayMs: record.appliedDelayMs,
    inflightRequestCount: record.inflightRequestCount,
  };
}

function useChallengeLogRecords(refreshToken: number) {
  const [records, setRecords] = useState<ChallengeLogRecord[] | null>(null);
  const [copyResult, setCopyResult] = useState<ChallengeLogCopyResult>("idle");

  useEffect(() => {
    let active = true;
    setCopyResult("idle");
    void readChallengeLog().then((storedRecords) => {
      if (active) {
        setRecords(storedRecords.map(allowlistedChallengeRecord));
      }
    });
    return () => {
      active = false;
    };
  }, [refreshToken]);

  const copyAllRecords = useCallback(async () => {
    if (!records || records.length === 0) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(records, null, 2));
      setCopyResult("success");
    } catch (error) {
      console.warn(
        "[suno-helper] challenge 履歴を clipboard へコピーできませんでした:",
        error
      );
      setCopyResult("failure");
    }
  }, [records]);

  return { copyAllRecords, copyResult, records };
}

function ChallengeLogFeedback({
  copyResult,
  records,
}: {
  copyResult: ChallengeLogCopyResult;
  records: ChallengeLogRecord[] | null;
}) {
  if (records === null) {
    return (
      <p data-suno-control="challenge-log-status" role="status">
        Challenge 履歴を読み込み中です。
      </p>
    );
  }
  if (records.length === 0) {
    return (
      <p data-suno-control="challenge-log-status" role="status">
        Challenge の記録はありません。
      </p>
    );
  }
  if (copyResult === "success") {
    return (
      <p data-suno-control="challenge-log-status" role="status">
        Challenge 履歴をコピーしました。
      </p>
    );
  }
  if (copyResult === "failure") {
    return (
      <p data-suno-control="challenge-log-error" role="alert">
        Challenge 履歴をコピーできませんでした。
      </p>
    );
  }
  return null;
}

function ChallengeRecordList({
  records,
}: {
  records: ChallengeLogRecord[] | null;
}) {
  const recentRecords =
    records?.slice(-RECENT_CHALLENGE_RECORD_COUNT).toReversed() ?? [];
  if (recentRecords.length === 0) return null;
  return (
    <ol className="mt-2 space-y-1">
      {recentRecords.map((record, index) => (
        <li
          data-suno-control="challenge-log-record"
          key={`${record.timestamp}-${record.source}-${index}`}
        >
          <time dateTime={new Date(record.timestamp).toISOString()}>
            {record.source} · {record.runMode ?? "run前"} · entry{" "}
            {record.entryIndex ?? "-"}/{record.total ?? "-"}
          </time>
        </li>
      ))}
    </ol>
  );
}

function ChallengeLogPanel({ refreshToken }: { refreshToken: number }) {
  const { copyAllRecords, copyResult, records } =
    useChallengeLogRecords(refreshToken);

  return (
    <section
      aria-labelledby="suno-challenge-log-title"
      className="mt-3 rounded-md border p-3 text-xs"
      data-suno-control="challenge-log"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-semibold" id="suno-challenge-log-title">
          Challenge 履歴
        </h2>
        <span data-suno-control="challenge-log-count">
          {records?.length ?? 0}件
        </span>
      </div>

      <ChallengeLogFeedback copyResult={copyResult} records={records} />
      <ChallengeRecordList records={records} />

      <button
        className="mt-2 rounded-md border px-2 py-1 disabled:cursor-not-allowed disabled:opacity-50"
        data-suno-control="copy-challenge-log"
        disabled={records === null || records.length === 0}
        onClick={() => void copyAllRecords()}
        type="button"
      >
        全件を JSON でコピー
      </button>
    </section>
  );
}

/**
 * Suno adapter for the shared overlay foundation. Messaging, copy and the
 * helper-specific storage key remain outside the service-neutral UI package.
 */
export function Overlay() {
  const [initial, setInitial] = useState<OverlayState | null | undefined>(
    undefined
  );
  const [reloadRequired, setReloadRequired] = useState(false);
  const [challengeLogRefreshToken, setChallengeLogRefreshToken] = useState(0);

  useEffect(() => {
    void (async () => {
      try {
        const version = browser.runtime.getManifest().version;
        const handshake = await sendMessage("extensionVersionHandshake", {
          version,
        });
        if (!handshake.matches) {
          setReloadRequired(true);
          return;
        }
        setInitial((await readOverlayState()) ?? null);
      } catch (error) {
        console.warn(
          "[suno-helper] overlay の初期化に失敗しました（拡張更新後はタブを再読み込みしてください）:",
          error
        );
        setReloadRequired(true);
      }
    })();
  }, []);

  const subscribeToggle = useCallback(
    (toggle: () => void) =>
      onMessage("toggleOverlay", () => {
        toggle();
        setChallengeLogRefreshToken((current) => current + 1);
      }),
    []
  );

  const handlePersistenceError = useCallback((error: unknown) => {
    console.warn(
      "[suno-helper] overlay state の保存に失敗しました（拡張更新後はタブを再読み込みしてください）:",
      error
    );
    setReloadRequired(true);
  }, []);

  if (reloadRequired) {
    return <ReloadRequiredNotice />;
  }
  if (initial === undefined) {
    return null;
  }

  return (
    <OverlayShell
      title="Suno Helper"
      initialState={initial}
      onStateChange={writeOverlayState}
      subscribeToggle={subscribeToggle}
      onError={handlePersistenceError}
      brandColors={SUNO_OVERLAY_BRAND}
    >
      <App />
      <ChallengeLogPanel refreshToken={challengeLogRefreshToken} />
    </OverlayShell>
  );
}
