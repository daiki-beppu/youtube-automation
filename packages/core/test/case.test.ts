import { describe, expect, test } from "bun:test";

// `snakeToCamel` is the shared, deep recursive camelization helper introduced
// for the zod retrofit (#825). Config sections declare schemas in snake_case
// (matching the JSON on disk) and pipe the parsed object through this helper in
// `.transform(...)` to produce the camelCase output shape the rest of the core
// consumes. The cases below are grounded in the exact keys that the existing
// config section tests require to flow through this function (audio / shorts /
// youtube.overlays / distrokid), so a regression here surfaces at the unit
// level before it reaches the section integration tests.
import { snakeToCamel } from "../internal/case.ts";

describe("snakeToCamel", () => {
  test("converts a single snake_case key to camelCase", () => {
    // Given a flat object with one snake_case key (audio.chapter_max)
    const input = { chapter_max: 100 };

    // When camelized
    const result = snakeToCamel(input) as Record<string, unknown>;

    // Then the key is camelCased and the value is untouched
    expect(result).toEqual({ chapterMax: 100 });
  });

  test("joins every segment of a multi-segment snake_case key", () => {
    // Given a key with several underscore segments
    // (shorts.min_hours_between_shorts_per_collection)
    const input = { min_hours_between_shorts_per_collection: 24 };

    // When camelized
    const result = snakeToCamel(input) as Record<string, unknown>;

    // Then all segments fold into one camelCase identifier
    expect(result).toEqual({ minHoursBetweenShortsPerCollection: 24 });
  });

  test("leaves single-word keys unchanged", () => {
    // Given keys that have no underscore to fold
    const input = { enabled: true, mode: "auto" };

    // When camelized
    const result = snakeToCamel(input) as Record<string, unknown>;

    // Then they pass through verbatim
    expect(result).toEqual({ enabled: true, mode: "auto" });
  });

  test("recurses into nested objects", () => {
    // Given a nested structure mirroring youtube.overlays
    const input = {
      audio_visualizer: { glow_sigma: 14, win_size: 4096 },
      subscribe_popup: { fade_sec: 0.8, start_sec: 8.5 },
    };

    // When camelized
    const result = snakeToCamel(input) as {
      audioVisualizer: Record<string, unknown>;
      subscribePopup: Record<string, unknown>;
    };

    // Then keys are camelized at every depth
    expect(result).toEqual({
      audioVisualizer: { glowSigma: 14, winSize: 4096 },
      subscribePopup: { fadeSec: 0.8, startSec: 8.5 },
    });
  });

  test("preserves an array of primitives verbatim", () => {
    // Given an array value of scalars (shorts.release.languages)
    const input = { languages: ["jp", "en"] };

    // When camelized
    const result = snakeToCamel(input) as Record<string, unknown>;

    // Then the array contents are preserved unchanged
    expect(result).toEqual({ languages: ["jp", "en"] });
  });

  test("camelizes objects nested inside arrays", () => {
    // Given an array whose elements are objects with snake_case keys
    // (deep recursion must descend through arrays, e.g. comments.rules)
    const input = { items: [{ first_name: "a" }, { last_name: "b" }] };

    // When camelized
    const result = snakeToCamel(input) as Record<string, unknown>;

    // Then each element's keys are camelized
    expect(result).toEqual({
      items: [{ firstName: "a" }, { lastName: "b" }],
    });
  });

  test("preserves scalar and null values", () => {
    // Given keys whose values are a number and an explicit null
    // (comments.generator.max_length / model)
    const input = { max_length: 280, target_duration_min: null };

    // When camelized
    const result = snakeToCamel(input) as Record<string, unknown>;

    // Then values are carried over unchanged (null stays null, not dropped)
    expect(result).toEqual({ maxLength: 280, targetDurationMin: null });
  });

  test("does not mutate the input object", () => {
    // Given an input object captured before the call
    const input = { artist_name: "City Nights", main_genre: "Electronic" };

    // When camelized
    snakeToCamel(input);

    // Then the original object retains its snake_case keys (pure function)
    expect(input).toEqual({
      artist_name: "City Nights",
      main_genre: "Electronic",
    });
  });
});
