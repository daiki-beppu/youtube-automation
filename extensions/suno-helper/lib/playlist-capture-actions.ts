// overlay の手動 Playlist Capture の Capture / Send 処理の純ロジック (#893 要件8)。
// @testing-library/react 未導入のため、React state を絡めた component 本体ではなく、capture/send の
// orchestration を純関数へ切り出して tester surface とする（resume-state.ts の resumeRunRange と同方針）。
// PlaylistCaptureTab.tsx はこの結果を setState へ写すだけのレンダ層に徹する。
import type { CapturedPlaylist, CapturedPlaylistsResult } from "../../shared/api";

/**
 * Capture の結果。`items` は成功時のみ（取得 0 件でも `[]` を載せる）。失敗時は undefined のまま
 * 既存 items を保持する。`status` / `isError` は overlay 下部の status 表示にそのまま使う。
 */
export interface CaptureOutcome {
  items?: CapturedPlaylist[];
  status: string;
  isError: boolean;
}

/**
 * 現在タブの runner content（background 中継）へ capturePlaylists を投げて結果を整形する。
 * 失敗時は items を更新せず、/me ページで実行する旨のエラー status を返す（fail-loud 表示）。
 */
export async function runCapture(sendCapture: () => Promise<CapturedPlaylist[]>): Promise<CaptureOutcome> {
  try {
    const items = await sendCapture();
    return { items, status: `${items.length} 件の playlist を取得しました。`, isError: false };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { status: `取得失敗: ${message}\nSuno の /me ページで実行してください。`, isError: true };
  }
}

/** Send の結果。status 表示用の文字列とエラー種別のみ（items は変えない）。 */
export interface SendOutcome {
  status: string;
  isError: boolean;
}

/**
 * 捕捉済み items をローカルサーバーへ POST し、レスポンスの {written, path} を status 文字列に整形する。
 *   - baseUrl 空: URL 入力を促すエラー（送信しない）。
 *   - items 空: 先に Capture を促すエラー（送信しない）。
 *   - POST 失敗: ステータスを含むエラー status（fail-loud 表示）。
 */
export async function runSend(
  baseUrl: string,
  items: CapturedPlaylist[],
  post: (baseUrl: string, items: CapturedPlaylist[]) => Promise<CapturedPlaylistsResult>,
): Promise<SendOutcome> {
  const trimmed = baseUrl.trim();
  if (!trimmed) {
    return { status: "サーバー URL を入力してください。", isError: true };
  }
  if (items.length === 0) {
    return { status: "先に Capture してください。", isError: true };
  }
  try {
    const result = await post(trimmed, items);
    return { status: `${result.written} 件を書き込みました: ${result.path}`, isError: false };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { status: `送信失敗: ${message}`, isError: true };
  }
}
