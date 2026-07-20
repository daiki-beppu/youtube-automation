import {
  Alert,
  AlertDescription,
  Button,
  Card,
  CardContent,
} from "@youtube-automation/ui";
import { useEffect, useState } from "react";
import { browser } from "wxt/browser";

import { COMMUNITY_PHASE, DEFAULT_URL } from "../../shared/constants";
import { onMessage, sendMessage, type ProgressMessage } from "../lib/messaging";

const INITIAL_PROGRESS: ProgressMessage[] = ([0, 1, 2] as const).map(
  (index) => ({
    index,
    phase: COMMUNITY_PHASE.SCHEDULING,
    message: "待機中",
    total: 3,
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
      if (
        data.phase === COMMUNITY_PHASE.DONE &&
        data.index === data.total - 1
      ) {
        setBusy(false);
      }
    });
    const unwatchError = onMessage("error", ({ data }) => {
      setError(data.message);
      setBusy(false);
    });
    return () => {
      unwatch();
      unwatchError();
    };
  }, []);

  const start = async () => {
    const baseUrl = serverUrl.trim().replace(/\/$/u, "");
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
      setBusy(false);
    }
  };

  const stop = async () => {
    try {
      await sendMessage("stop");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="space-y-4 bg-background p-4 text-foreground">
      <label className="block text-sm font-medium">
        サーバー URL
        <input
          className="mt-1 w-full rounded border border-input bg-background px-2 py-1"
          name="serverUrl"
          onChange={(event) => setServerUrl(event.target.value)}
          type="url"
          value={serverUrl}
        />
      </label>
      <div className="flex gap-2">
        <Button
          className="flex-1"
          disabled={busy}
          onClick={() => void start()}
          type="button"
        >
          {busy ? "Running…" : "Start"}
        </Button>
        <Button
          disabled={!busy}
          onClick={() => void stop()}
          type="button"
          variant="outline"
        >
          Stop
        </Button>
      </div>
      {error ? (
        <Alert role="alert" variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <ol className="space-y-2" aria-label="投稿進捗">
        {progress.map((item) => (
          <li data-testid="progress-row" key={item.index}>
            <Card>
              <CardContent className="p-2 text-sm">
                <span className="font-medium">投稿 {item.index + 1}</span>
                <span className="ml-2 text-muted-foreground">
                  {item.message}
                </span>
              </CardContent>
            </Card>
          </li>
        ))}
      </ol>
    </main>
  );
}
