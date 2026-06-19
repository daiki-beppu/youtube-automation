import { describe, expect, mock, test } from "bun:test";

import type { SleepMs } from "@youtube-automation/core";
import { generateImageService } from "@youtube-automation/core/image";
import type {
  GenerateImageInput,
  ImageProvider,
  PersistImage,
} from "@youtube-automation/core/image";

type ProviderBehavior = Uint8Array | Error;
const baseInput = (
  overrides: Partial<GenerateImageInput>
): GenerateImageInput =>
  ({
    aspectRatio: "16:9",
    imageSize: "2K",
    outputPath: "/tmp/generated-image.png",
    prompt: "a quiet neon studio at midnight",
    ...overrides,
  }) as GenerateImageInput;

const fakeProvider = (behaviors: ProviderBehavior[]) => {
  let callIndex = 0;
  const generate = mock((_request: GenerateImageInput) => {
    const behavior = behaviors[callIndex];
    callIndex += 1;
    return Promise.resolve().then(() => {
      if (behavior === undefined) {
        throw new Error("fake image provider: no behavior queued");
      }
      if (behavior instanceof Error) {
        throw behavior;
      }
      return behavior;
    });
  });
  const provider: ImageProvider = {
    generate,
    name: "fake",
    supportedAspectRatios: [],
  };
  return { generate, provider };
};

const fakePersist = (): PersistImage =>
  mock((path: string) => Promise.resolve(path));

const recordSleep = (): SleepMs => mock(() => Promise.resolve());

const enospcPersist: PersistImage = () =>
  Promise.reject(
    Object.assign(new Error("ENOSPC: no space left on device"), {
      code: "ENOSPC",
    })
  );

describe("generateImageService orchestration", () => {
  test("should persist provider bytes and return the saved path when generation succeeds", async () => {
    const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
    const outputPath = "/tmp/success.png";
    const { generate, provider } = fakeProvider([bytes]);
    const persist = fakePersist();
    const result = await generateImageService(baseInput({ outputPath }), {
      persist,
      provider,
      sleep: recordSleep(),
    });
    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok result, got ${result.error.domain}`);
    }
    expect(result.value).toEqual({ savedPath: outputPath });
    expect(generate).toHaveBeenCalledTimes(1);
    expect(persist).toHaveBeenCalledTimes(1);
    expect(persist).toHaveBeenCalledWith(outputPath, bytes);
  });

  test("should return a validation error before calling provider when input is invalid", async () => {
    const { generate, provider } = fakeProvider([
      new Uint8Array([0xff, 0xd8, 0xff]),
    ]);
    const persist = fakePersist();
    const invalidInput = {
      aspectRatio: "16:9",
      imageSize: "2K",
      prompt: "missing output path",
    } as unknown as GenerateImageInput;
    const result = await generateImageService(invalidInput, {
      persist,
      provider,
      sleep: recordSleep(),
    });
    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation error result");
    }
    expect(result.error.domain).toBe("validation");
    expect(generate).not.toHaveBeenCalled();
    expect(persist).not.toHaveBeenCalled();
  });

  test("should not retry provider calls when the error is content policy related", async () => {
    const { generate, provider } = fakeProvider([
      new Error("blocked due to SAFETY filters"),
    ]);
    const sleep = recordSleep();
    const result = await generateImageService(baseInput({}), {
      persist: fakePersist(),
      provider,
      sleep,
    });
    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected content policy error result");
    }
    expect(result.error.domain).toBe("io");
    expect(result.error.message).toContain("SAFETY");
    expect(generate).toHaveBeenCalledTimes(1);
    expect(sleep).not.toHaveBeenCalled();
  });

  test("should retry a transient provider error when a later attempt succeeds", async () => {
    const bytes = new Uint8Array([1, 2, 3, 4]);
    const { generate, provider } = fakeProvider([
      new Error("503 backend unavailable"),
      bytes,
    ]);
    const sleep = recordSleep();
    const persist = fakePersist();
    const result = await generateImageService(baseInput({}), {
      persist,
      provider,
      sleep,
    });
    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected retry success, got ${result.error.domain}`);
    }
    expect(generate).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenCalledTimes(1);
    expect(sleep).toHaveBeenCalledWith(10_000);
    expect(persist).toHaveBeenCalledWith("/tmp/generated-image.png", bytes);
  });

  test("should map persist failures to an io error when saving fails", async () => {
    const { generate, provider } = fakeProvider([new Uint8Array([5, 6, 7])]);
    const result = await generateImageService(baseInput({}), {
      persist: enospcPersist,
      provider,
      sleep: recordSleep(),
    });
    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected persist error result");
    }
    expect(result.error.domain).toBe("io");
    expect(result.error.message).toContain("ENOSPC");
    expect(generate).toHaveBeenCalledTimes(1);
  });

  test("should return the final provider error when retry attempts are exhausted", async () => {
    const { generate, provider } = fakeProvider([
      new Error("first transient error"),
      new Error("second transient error"),
      new Error("final transient error"),
    ]);
    const sleep = recordSleep();
    const persist = fakePersist();
    const result = await generateImageService(baseInput({}), {
      persist,
      provider,
      sleep,
    });
    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected exhausted retry error result");
    }
    expect(result.error.domain).toBe("io");
    expect(result.error.message).toBe("final transient error");
    expect(generate).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenNthCalledWith(1, 10_000);
    expect(sleep).toHaveBeenNthCalledWith(2, 30_000);
    expect(persist).not.toHaveBeenCalled();
  });
});
