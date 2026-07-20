// runtime messaging は JSON 直列化されるため Blob/File を base64 wire に変換する。
export interface SerializedAsset {
  base64: string;
  filename: string;
  mimeType: string;
}

const CHUNK_SIZE = 0x8000;

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += CHUNK_SIZE) {
    binary += String.fromCharCode(
      ...bytes.subarray(offset, offset + CHUNK_SIZE)
    );
  }
  return btoa(binary);
}

function base64ToBytes(base64: string): Uint8Array<ArrayBuffer> {
  const binary = atob(base64);
  const buffer = new ArrayBuffer(binary.length);
  const bytes = new Uint8Array(buffer);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

export async function encodeAsset(
  filename: string,
  blob: Blob
): Promise<SerializedAsset> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  return { base64: bytesToBase64(bytes), filename, mimeType: blob.type };
}

export function decodeAsset(asset: SerializedAsset): File {
  return new File([base64ToBytes(asset.base64)], asset.filename, {
    type: asset.mimeType,
  });
}
