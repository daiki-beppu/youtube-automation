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

/**
 * CORS 判定。
 *
 * - `allowOrigin === null`  → `chrome-extension://` scheme のみ許可
 * - `allowOrigin` 指定時     → その値との完全一致のみ許可 (scheme 不問)
 * - origin が空/欠落         → 常に false
 */
export function isOriginAllowed(
  origin: string | null | undefined,
  allowOrigin: string | null,
): boolean {
  if (!origin) {
    return false;
  }
  if (allowOrigin !== null) {
    return origin === allowOrigin;
  }
  return origin.startsWith(EXTENSION_ORIGIN_SCHEME);
}
