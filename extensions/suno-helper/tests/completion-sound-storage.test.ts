import { beforeEach, describe, expect, it, vi } from "vitest";

const soundSettingsItem = vi.hoisted(() => ({
  getValue: vi.fn(),
  setValue: vi.fn(async () => undefined),
}));

vi.mock("wxt/utils/storage", () => ({
  storage: { defineItem: vi.fn(() => soundSettingsItem) },
}));

import { readCompletionSoundSettings } from "../lib/storage";

describe("completion sound storage (#2077)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    soundSettingsItem.setValue.mockResolvedValue(undefined);
  });

  it("未設定は default ON + chime を返して永続化する", async () => {
    soundSettingsItem.getValue.mockResolvedValue(undefined);

    await expect(readCompletionSoundSettings()).resolves.toEqual({
      enabled: true,
      preset: "chime",
    });
    expect(soundSettingsItem.setValue).toHaveBeenCalledWith({
      enabled: true,
      preset: "chime",
    });
  });

  it("保存済みの OFF + preset をそのまま復元する", async () => {
    soundSettingsItem.getValue.mockResolvedValue({
      enabled: false,
      preset: "bell",
    });

    await expect(readCompletionSoundSettings()).resolves.toEqual({
      enabled: false,
      preset: "bell",
    });
    expect(soundSettingsItem.setValue).not.toHaveBeenCalled();
  });

  it("不正値は default に自己修復する", async () => {
    soundSettingsItem.getValue.mockResolvedValue({
      enabled: "yes",
      preset: "noise",
    });

    await expect(readCompletionSoundSettings()).resolves.toEqual({
      enabled: true,
      preset: "chime",
    });
    expect(soundSettingsItem.setValue).toHaveBeenCalledWith({
      enabled: true,
      preset: "chime",
    });
  });
});
