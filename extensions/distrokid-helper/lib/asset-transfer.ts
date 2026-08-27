// overlay が生成した Blob URL を、同一タブの content script で File に復元する。
export async function blobUrlToFile(
  blobUrl: string,
  filename: string
): Promise<File> {
  const blob = await fetch(blobUrl).then((response) => response.blob());
  return new File([blob], filename, { type: blob.type });
}
