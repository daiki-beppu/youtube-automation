interface RemovableStorageItem {
  removeValue(): Promise<void>;
}

export async function migrateLegacyServerSources(
  item: RemovableStorageItem,
): Promise<void> {
  await item.removeValue();
}
