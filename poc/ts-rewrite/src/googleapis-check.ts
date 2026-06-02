import { google } from "googleapis";
import type { CheckResult } from "./types";

const CHECK_NAME = "googleapis";

/**
 * 空 auth で youtube.channels.list を呼び、認証拒否エラーになることを確認する。
 * エラーが返ること自体が「ライブラリが bun でロード・実行できた」証拠になる。
 * 認証が通ってしまう（成功）のは想定外なので FAIL とする。
 */
export async function checkGoogleapis(): Promise<CheckResult> {
  const youtube = google.youtube("v3");
  try {
    await youtube.channels.list({ part: ["snippet"], mine: true });
    return {
      name: CHECK_NAME,
      ok: false,
      detail: "empty auth でも呼び出しが成功してしまった（想定外）",
    };
  } catch (error) {
    return classifyAuthError(error);
  }
}

function classifyAuthError(error: unknown): CheckResult {
  const message = error instanceof Error ? error.message : String(error);
  const code = (error as { code?: number | string }).code;
  const ok = code === 401 || code === 403; // 401 / 403(PERMISSION_DENIED) のみを合格とする
  return {
    name: CHECK_NAME,
    ok,
    detail: `code=${code ?? "n/a"} message=${message}`,
  };
}
