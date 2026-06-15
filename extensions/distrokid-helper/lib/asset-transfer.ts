// asset（曲 / ジャケット）を popup ↔ content 間で受け渡すための直列化。
//
// なぜ popup 側で fetch するのか:
//   #896 で yt-collection-serve（collection_serve.py の is_origin_allowed）が
//   デフォルトで distrokid.com origin も許可するようになったが、distrokid-helper 本体を
//   content script fetch へ書き換えるのは #896 のスコープ外（別 issue）。現状は fetch を
//   拡張コンテキスト（popup, `chrome-extension://` origin）で行い、
//   取得した File のバイト列を base64 で content へ転送する構成を維持する。
//   （@webext-core/messaging は runtime メッセージを JSON 直列化するため File/Blob を
//    そのまま渡せない。base64 文字列に変換して転送する。）

// popup -> content へ転送する asset の直列化形式。
export interface SerializedAsset {
  filename: string;
  mimeType: string;
  base64: string;
}

// chunk 単位で fromCharCode に渡す（大きな配列を一括展開するとスタック超過するため）。
const CHUNK_SIZE = 0x8000;

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += CHUNK_SIZE) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + CHUNK_SIZE));
  }
  return btoa(binary);
}

// File / Blob の BlobPart は ArrayBuffer 裏付けの view を要求するため、
// 明示的に ArrayBuffer 上へ確保する（TS 5.7 の Uint8Array<ArrayBufferLike> 回避）。
function base64ToBytes(base64: string): Uint8Array<ArrayBuffer> {
  const binary = atob(base64);
  const buffer = new ArrayBuffer(binary.length);
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

// 取得済み blob を転送用に直列化する（popup 側で実行）。
export async function encodeAsset(filename: string, blob: Blob): Promise<SerializedAsset> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  return { filename, mimeType: blob.type, base64: bytesToBase64(bytes) };
}

// 直列化された asset を注入用の File へ復元する（content 側で実行）。
export function decodeAsset(asset: SerializedAsset): File {
  const bytes = base64ToBytes(asset.base64);
  return new File([bytes], asset.filename, { type: asset.mimeType });
}
