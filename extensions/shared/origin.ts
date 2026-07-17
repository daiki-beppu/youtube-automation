// origin allowlist は yt-collection-serve の CORS 判定
// (`collection_serve.py::is_origin_allowed`) と対の契約。サーバー側 SSOT の
// 各分岐を拡張側でも同じ真偽値で再現する。
//
// NOTE: これは「実行時消費者を持たない契約パリティ用ミラー」である。
// クライアント側で CORS gating を行う構造はなく（CORS はサーバーが応答ヘッダで制御）、
// 本関数の唯一の利用者は `tests/origin.test.ts`。order 要件 #8/#10 が origin allowlist を
// shared へ抽出し単体テスト対象とすることを明示しているため、未使用 export ではなく
// 意図された成果物として残置する。サーバー側ロジックを変更したら本ミラーも追従させること。

const EXTENSION_ORIGIN_SCHEME = "chrome-extension://";

// overlay 化（#892/#895）で content script の fetch が page origin になったため、
// helper 拡張がホストされる web origin をデフォルト許可する（#896）。完全一致のみ。
// サーバー側 SSOT `collection_serve.py::_DEFAULT_ALLOWED_WEB_ORIGINS` と同値。
const DEFAULT_ALLOWED_WEB_ORIGINS = new Set([
  "https://suno.com",
  "https://www.suno.com",
  "https://distrokid.com",
  "https://www.distrokid.com",
]);

/**
 * CORS 判定。
 *
 * - `allowOrigin === null`  → `chrome-extension://` scheme + helper サイト web origin
 *                             （suno.com / distrokid.com、完全一致）を許可（#896）
 * - `allowOrigin` 指定時     → その値との完全一致のみ許可 (scheme 不問)
 * - origin が空/欠落         → 常に false
 */
export function isOriginAllowed(
  origin: string | null | undefined,
  allowOrigin: string | null
): boolean {
  if (!origin) {
    return false;
  }
  if (allowOrigin !== null) {
    return origin === allowOrigin;
  }
  if (origin.startsWith(EXTENSION_ORIGIN_SCHEME)) {
    return true;
  }
  return DEFAULT_ALLOWED_WEB_ORIGINS.has(origin);
}
