// Tests for packages/core/src/image config parsing + provider dispatch — the TS
// port of the pure config surface from Python `utils/image_provider/config.py`
// and `utils/image_provider/__init__.py::get_provider`.
//
// Signature contract (test-first spec the draft implements), from plan §6/§7:
//   OPENAI_SUPPORTED_ASPECT_RATIOS = ["16:9", "9:16"]
//   parseImageGenerationConfig(raw: unknown): ImageGenerationConfig
//   getProvider(config: ImageGenerationConfig, deps?): ImageProvider
//
// Scope note (plan §4-D): legacy `gemini_image:` namespace, `gemini_cli`/`codex`
// providers, `thinking`, and `replace_model` are intentionally NOT ported, so an
// unsupported `provider` value (including "codex"/"gemini_cli") must fail fast
// with a `config:`-prefixed Error. Input keys are snake_case (matching the
// existing config parsers); the parsed result is camelCase.

import { describe, expect, test } from "bun:test";

import {
  getProvider,
  OPENAI_SUPPORTED_ASPECT_RATIOS,
  parseImageGenerationConfig,
} from "@youtube-automation/core/image";
import type { ImageGenerationConfig } from "@youtube-automation/core/image";

// --- shared aspect-ratio constants -----------------------------------------
// (RETRY_MAX / RETRY_BACKOFF were promoted into the withRetry defaults in
// #959 and are asserted behaviorally in retry.test.ts.)

describe("aspect-ratio constants", () => {
  test("OPENAI_SUPPORTED_ASPECT_RATIOS is exactly 16:9 and 9:16 (config.py:24)", () => {
    // Given OpenAI's restricted aspect-ratio set
    // When reading the exported tuple
    // Then only the two landscape/portrait ratios are allowed
    expect([...OPENAI_SUPPORTED_ASPECT_RATIOS]).toEqual(["16:9", "9:16"]);
  });
});

// --- parseImageGenerationConfig: defaults --------------------------------

describe("parseImageGenerationConfig defaults", () => {
  test("falls back to the gemini provider when no image_generation namespace exists", () => {
    // Given a raw config with no image_generation section (config.py:145)
    const config = parseImageGenerationConfig({});
    // When parsing it
    // Then the gemini provider default is selected with its model/size defaults
    expect(config.provider).toBe("gemini");
    if (config.provider !== "gemini") {
      throw new Error("expected gemini provider");
    }
    expect(config.gemini.model).toBe("gemini-3.1-flash-image-preview");
    expect(config.gemini.imageSize).toBe("2K");
  });

  test("fills gemini defaults when the gemini sub-config is empty", () => {
    // Given provider=gemini with no sub-keys (config.py:177-181)
    const config = parseImageGenerationConfig({
      image_generation: { provider: "gemini" },
    });
    // When parsing it
    // Then the model and image_size defaults are applied
    if (config.provider !== "gemini") {
      throw new Error("expected gemini provider");
    }
    expect(config.gemini.model).toBe("gemini-3.1-flash-image-preview");
    expect(config.gemini.imageSize).toBe("2K");
  });

  test("fills openai defaults when the openai sub-config is empty", () => {
    // Given provider=openai with no sub-keys (config.py:192-199)
    const config = parseImageGenerationConfig({
      image_generation: { provider: "openai" },
    });
    // When parsing it
    // Then model/quality/aspectRatio/batch defaults are applied
    if (config.provider !== "openai") {
      throw new Error("expected openai provider");
    }
    expect(config.openai.model).toBe("gpt-image-2");
    expect(config.openai.quality).toBe("high");
    expect(config.openai.aspectRatio).toBe("16:9");
    expect(config.openai.batch).toBe(1);
  });
});

// --- parseImageGenerationConfig: overrides (snake_case input) -------------

describe("parseImageGenerationConfig overrides", () => {
  test("reads snake_case image_size into the camelCase gemini field", () => {
    // Given a gemini override using the snake_case input key
    const config = parseImageGenerationConfig({
      image_generation: {
        gemini: { image_size: "4K", model: "gemini-x" },
        provider: "gemini",
      },
    });
    // When parsing it
    // Then the override values land on the camelCase output fields
    if (config.provider !== "gemini") {
      throw new Error("expected gemini provider");
    }
    expect(config.gemini.model).toBe("gemini-x");
    expect(config.gemini.imageSize).toBe("4K");
  });

  test("reads snake_case aspect_ratio + batch into the openai sub-config", () => {
    // Given an openai override with the portrait ratio and a batch size
    const config = parseImageGenerationConfig({
      image_generation: {
        openai: {
          aspect_ratio: "9:16",
          batch: 3,
          model: "gpt-image-2",
          quality: "medium",
        },
        provider: "openai",
      },
    });
    // When parsing it
    // Then the camelCase output reflects every override
    if (config.provider !== "openai") {
      throw new Error("expected openai provider");
    }
    expect(config.openai.quality).toBe("medium");
    expect(config.openai.aspectRatio).toBe("9:16");
    expect(config.openai.batch).toBe(3);
  });
});

// --- parseImageGenerationConfig: fail-fast --------------------------------

describe("parseImageGenerationConfig fail-fast", () => {
  test("rejects an OpenAI aspect_ratio outside the supported set", () => {
    // Given an openai config with an unsupported ratio (config.py:87-92)
    // When parsing it
    // Then it fails fast rather than producing an invalid config
    expect(() =>
      parseImageGenerationConfig({
        image_generation: {
          openai: { aspect_ratio: "1:1" },
          provider: "openai",
        },
      })
    ).toThrow(/^config:/u);
  });

  test("rejects an unsupported provider name", () => {
    // Given a provider value outside {gemini, openai} (config.py:150-151)
    // When parsing it
    // Then a config:-prefixed Error is raised
    expect(() =>
      parseImageGenerationConfig({
        image_generation: { provider: "midjourney" },
      })
    ).toThrow(/^config:/u);
  });

  test("rejects the de-scoped codex provider", () => {
    // Given provider=codex, which is intentionally NOT ported (plan §4-D)
    // When parsing it
    // Then it is treated as unsupported, not silently accepted
    expect(() =>
      parseImageGenerationConfig({
        image_generation: { provider: "codex" },
      })
    ).toThrow(/^config:/u);
  });

  test("rejects the de-scoped gemini_cli provider", () => {
    // Given provider=gemini_cli, which is intentionally NOT ported (plan §4-D)
    // When parsing it
    // Then it is treated as unsupported
    expect(() =>
      parseImageGenerationConfig({
        image_generation: { provider: "gemini_cli" },
      })
    ).toThrow(/^config:/u);
  });
});

// --- getProvider dispatch -------------------------------------------------

describe("getProvider dispatch", () => {
  test("returns a gemini provider with no aspect-ratio restriction", () => {
    // Given a parsed gemini config
    const config = parseImageGenerationConfig({
      image_generation: { provider: "gemini" },
    });
    // When dispatching to a provider
    const provider = getProvider(config);
    // Then the gemini provider exposes its identifier and an empty (unrestricted)
    // aspect-ratio set (gemini.py:27-29)
    expect(provider.name).toBe("gemini");
    expect([...provider.supportedAspectRatios]).toEqual([]);
  });

  test("returns an openai provider restricted to 16:9 and 9:16", () => {
    // Given a parsed openai config
    const config = parseImageGenerationConfig({
      image_generation: { provider: "openai" },
    });
    // When dispatching to a provider
    const provider = getProvider(config);
    // Then the openai provider advertises its restricted ratios (openai.py:43-44)
    expect(provider.name).toBe("openai");
    expect([...provider.supportedAspectRatios]).toEqual(["16:9", "9:16"]);
  });

  test("fails fast on an unsupported provider in the config", () => {
    // Given a hand-rolled config carrying an unsupported provider (__init__.py:75)
    const bogus = { provider: "codex" } as unknown as ImageGenerationConfig;
    // When dispatching it
    // Then getProvider raises a config:-prefixed Error rather than returning undefined
    expect(() => getProvider(bogus)).toThrow(/^config:/u);
  });
});
