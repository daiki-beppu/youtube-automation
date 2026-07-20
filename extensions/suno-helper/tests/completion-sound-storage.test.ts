import { beforeEach, describe, expect, it, vi } from "vitest";

const soundSettingsItem = vi.hoisted(() => ({
  getValue: vi.fn(),
  setValue: vi.fn(async () => undefined),
}));

vi.mock("wxt/utils/storage", () => ({
  storage: { defineItem: vi.fn(() => soundSettingsItem) },
}));

import { readCompletionSoundSettings } from "../lib/storage";

describe("notification settings storage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    soundSettingsItem.setValue.mockResolvedValue(undefined);
  });

  it("未設定は default ON を返して永続化する", async () => {
    soundSettingsItem.getValue.mockResolvedValue(undefined);
    await expect(readCompletionSoundSettings()).resolves.toEqual({
      enabled: true,
    });
    expect(soundSettingsItem.setValue).toHaveBeenCalledWith({ enabled: true });
  });

  it("旧 OFF + preset は OFF を維持して preset を削除する", async () => {
    soundSettingsItem.getValue.mockResolvedValue({
      enabled: false,
      preset: "bell",
    });
    await expect(readCompletionSoundSettings()).resolves.toEqual({
      enabled: false,
    });
    expect(soundSettingsItem.setValue).toHaveBeenCalledWith({ enabled: false });
  });

  it("不正値は default に自己修復する", async () => {
    soundSettingsItem.getValue.mockResolvedValue({ enabled: "yes" });
    await expect(readCompletionSoundSettings()).resolves.toEqual({
      enabled: true,
    });
    expect(soundSettingsItem.setValue).toHaveBeenCalledWith({ enabled: true });
  });
});
