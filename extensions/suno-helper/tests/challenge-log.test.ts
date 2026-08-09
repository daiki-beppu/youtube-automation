import { beforeEach, describe, expect, it, vi } from "vitest";

const challengeStorage = vi.hoisted(() => {
  let value: unknown[] = [];
  const getValue = vi.fn(async () => [...value]);
  const setValue = vi.fn(async (next: unknown[]) => {
    value = [...next];
  });
  const defineItem = vi.fn(() => ({ getValue, setValue }));
  return {
    defineItem,
    getValue,
    setValue,
    read: () => [...value],
    reset: () => {
      value = [];
      defineItem.mockClear();
      getValue.mockReset().mockImplementation(async () => [...value]);
      setValue.mockReset().mockImplementation(async (next: unknown[]) => {
        value = [...next];
      });
    },
  };
});

vi.mock("wxt/utils/storage", () => ({
  storage: { defineItem: challengeStorage.defineItem },
}));

function record(timestamp: number) {
  return {
    timestamp,
    source: "before-create" as const,
    runMode: "queue" as const,
    unattended: true,
    entryIndex: 2,
    total: 10,
    challengeLevel: 1,
    recentCreateCount: 4,
  };
}

describe("challenge log storage boundary (#2982)", () => {
  beforeEach(() => {
    vi.resetModules();
    challengeStorage.reset();
  });

  it("storage item を local key と空配列 fallback で遅延定義する", async () => {
    const { readChallengeLog } = await import("../lib/challenge-log");

    expect(challengeStorage.defineItem).not.toHaveBeenCalled();
    await expect(readChallengeLog()).resolves.toEqual([]);

    expect(challengeStorage.defineItem).toHaveBeenCalledOnce();
    expect(challengeStorage.defineItem).toHaveBeenCalledWith(
      "local:sunoChallengeLog",
      { fallback: [] }
    );
  });

  it("上限超過時に最古から破棄し、run を跨ぐ逐次 append の順序を保持する", async () => {
    const { appendChallengeRecord, CHALLENGE_LOG_MAX_RECORDS } =
      await import("../lib/challenge-log");

    for (
      let timestamp = 0;
      timestamp < CHALLENGE_LOG_MAX_RECORDS + 2;
      timestamp += 1
    ) {
      await appendChallengeRecord(record(timestamp));
    }

    const stored = challengeStorage.read() as Array<{ timestamp: number }>;
    expect(stored).toHaveLength(CHALLENGE_LOG_MAX_RECORDS);
    expect(stored.map(({ timestamp }) => timestamp)).toEqual(
      Array.from({ length: CHALLENGE_LOG_MAX_RECORDS }, (_, index) => index + 2)
    );
  });

  it("allowlist field だけを再構築し、生成内容や認証情報を保存しない", async () => {
    const { appendChallengeRecord } = await import("../lib/challenge-log");
    const input = {
      ...record(100),
      style: "secret style",
      lyrics: "secret lyrics",
      token: "secret token",
      authorization: "Bearer secret",
    };

    await appendChallengeRecord(input);

    expect(challengeStorage.read()).toEqual([record(100)]);
  });

  it("storage の read / write failure を呼び出し元へ伝播しない", async () => {
    const { appendChallengeRecord, readChallengeLog } =
      await import("../lib/challenge-log");
    challengeStorage.getValue.mockRejectedValueOnce(new Error("read failed"));

    await expect(appendChallengeRecord(record(1))).resolves.toBeUndefined();

    challengeStorage.getValue.mockRejectedValueOnce(new Error("read failed"));
    await expect(readChallengeLog()).resolves.toEqual([]);
    challengeStorage.setValue.mockRejectedValueOnce(new Error("write failed"));
    await expect(appendChallengeRecord(record(2))).resolves.toBeUndefined();
  });

  it("同時 append を直列化して lost update を防ぐ", async () => {
    const { appendChallengeRecord } = await import("../lib/challenge-log");

    await Promise.all([
      appendChallengeRecord(record(1)),
      appendChallengeRecord(record(2)),
      appendChallengeRecord(record(3)),
    ]);

    expect(challengeStorage.read()).toEqual([record(1), record(2), record(3)]);
  });
});
