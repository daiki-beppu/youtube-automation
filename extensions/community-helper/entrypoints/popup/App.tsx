import { useEffect, useState } from "react";
import { browser } from "wxt/browser";

import { COMMUNITY_PHASE, DEFAULT_URL } from "../../../shared/constants";
import {
  onMessage,
  sendMessage,
  type ProgressMessage,
} from "../../lib/messaging";

const INITIAL_PROGRESS: ProgressMessage[] = ([0, 1, 2] as const).map(
  (index) => ({
    index,
    phase: COMMUNITY_PHASE.SCHEDULING,
    message: "待機中",
  })
);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function App() {
  const [serverUrl, setServerUrl] = useState<string>(DEFAULT_URL);
  const [progress, setProgress] = useState(INITIAL_PROGRESS);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const unwatch = onMessage("progress", ({ data }) => {
      setProgress((current) =>
        current.map((item) => (item.index === data.index ? data : item))
      );
    });
    return () => unwatch();
  }, []);

  const start = async () => {
    const baseUrl = serverUrl.trim().replace(/\/$/, "");
    setError(null);
    setBusy(true);
    try {
      if (baseUrl.length === 0) {
        throw new Error("サーバー URL を入力してください");
      }
      const result = await sendMessage("checkCompatibility", {
        baseUrl,
        extensionVersion: browser.runtime.getManifest().version,
      });
      if (result.status !== "compatible") {
        if (result.status === "incompatible") {
          throw new Error(
            `拡張 ${result.extensionVersion} はサーバーの最低要求 ${result.minExtensionVersion} と互換性がありません`
          );
        }
        if (result.status === "error") {
          throw new Error(result.message);
        }
        throw new Error("サーバーの /version を確認できません");
      }
      await sendMessage("run", { baseUrl });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="space-y-4 p-4">
      <h1 className="text-lg font-semibold">Community Helper</h1>
      <label className="block text-sm font-medium">
        サーバー URL
        <input
          className="mt-1 w-full rounded border px-2 py-1"
          name="serverUrl"
          onChange={(event) => setServerUrl(event.target.value)}
          type="url"
          value={serverUrl}
        />
      </label>
      <button
        className="w-full rounded bg-red-600 px-3 py-2 font-medium text-white disabled:opacity-50"
        disabled={busy}
        onClick={() => void start()}
        type="button"
      >
        {busy ? "Checking…" : "Start"}
      </button>
      {error ? (
        <p className="text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}
      <ol className="space-y-2" aria-label="投稿進捗">
        {progress.map((item) => (
          <li
            className="rounded border p-2 text-sm"
            data-testid="progress-row"
            key={item.index}
          >
            <span className="font-medium">投稿 {item.index + 1}</span>
            <span className="ml-2 text-neutral-600">{item.message}</span>
          </li>
        ))}
      </ol>
    </main>
  );
}
