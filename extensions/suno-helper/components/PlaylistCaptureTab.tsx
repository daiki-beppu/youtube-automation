// overlay 下部の Suno playlist capture セクション (#893)。
// Capture（runner content 経由で現在ページ `/me` の playlist を scrape）→ Send to localhost
// （POST /suno/playlists でサーバーへ書き込み）の 2 ボタンで完結する。prefix フィルタは
// サーバー側 normalize_suno_title に閉じるため、ここは全件そのまま送る（channel-agnostic）。
import { useCallback, useState } from "react";

import { type CapturedPlaylist, postCapturedPlaylists } from "../../shared/api";
import { sendMessage } from "../lib/messaging";
import { runCapture, runSend } from "../lib/playlist-capture-actions";

/** baseUrl は overlay の「サーバー URL」入力（useSunoRunner の url）をそのまま受け取る。 */
export function PlaylistCaptureTab({ baseUrl }: { baseUrl: string }) {
  const [items, setItems] = useState<CapturedPlaylist[]>([]);
  const [status, setStatus] = useState("");
  const [isError, setIsError] = useState(false);

  const report = useCallback((text: string, error: boolean) => {
    setStatus(text);
    setIsError(error);
  }, []);

  // 現在タブの runner content（background 中継）へ capturePlaylists を投げて scrape 結果を受け取る。
  const capture = useCallback(async () => {
    const outcome = await runCapture(() => sendMessage("capturePlaylists", undefined));
    if (outcome.items !== undefined) {
      setItems(outcome.items);
    }
    report(outcome.status, outcome.isError);
  }, [report]);

  // 捕捉済み items をローカルサーバーへ POST する。レスポンスの {written, path} を status に出す。
  const send = useCallback(async () => {
    const outcome = await runSend(baseUrl, items, postCapturedPlaylists);
    report(outcome.status, outcome.isError);
  }, [baseUrl, items, report]);

  return (
    <fieldset className="flex flex-col gap-2 rounded border border-gray-200 px-2 py-2 text-sm">
      <legend className="px-1 text-xs text-gray-600">Playlist Capture</legend>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void capture()}
          className="flex-1 rounded bg-gray-800 px-2 py-1 text-sm text-white hover:bg-gray-700"
        >
          Capture
        </button>
        <button
          type="button"
          onClick={() => void send()}
          disabled={items.length === 0}
          className="flex-1 rounded bg-blue-600 px-2 py-1 text-sm text-white hover:bg-blue-500 disabled:opacity-40"
        >
          Send to localhost
        </button>
      </div>

      {items.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-xs text-gray-700">
          {items.map((item) => (
            <li key={item.url} className="truncate">
              {item.title}
            </li>
          ))}
        </ul>
      )}

      {status && (
        <p className={`whitespace-pre-wrap text-xs ${isError ? "text-red-600" : "text-gray-600"}`}>{status}</p>
      )}
    </fieldset>
  );
}
