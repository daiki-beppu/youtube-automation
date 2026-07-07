// Tests for the template loader (plan §4-C). The description templates live in
// packages/core/templates/ and are resolved relative to the module via
// import.meta — NOT via process.cwd() — so the loader works regardless of the
// caller's working directory.
//
// These assertions pin the *machine* contract (the {placeholder} tokens the
// str.format pipeline consumes), not the prose of the template, so they remain
// valid even if the surrounding copy is reworded.

import { describe, expect, test } from "bun:test";

import { loadTemplate } from "../src/templates.ts";

describe("loadTemplate", () => {
  test("loads the complete-collection template with its format placeholders", () => {
    const tpl = loadTemplate("complete_collection");

    expect(tpl).toContain("{collection_name}");
    expect(tpl).toContain("{timestamp_list}");
    expect(tpl).toContain("{hashtag_line}");
  });

  test("loads the individual-track template with its format placeholders", () => {
    const tpl = loadTemplate("individual_track");

    expect(tpl).toContain("{track_title}");
    expect(tpl).toContain("{collection_url}");
  });

  test("resolves the same content regardless of process.cwd()", () => {
    // Given a different working directory than the package root
    const original = process.cwd();
    try {
      process.chdir("/");

      // When loading the template from an unrelated cwd
      // Then import.meta-based resolution still finds the resource
      expect(loadTemplate("complete_collection")).toContain(
        "{collection_name}"
      );
    } finally {
      process.chdir(original);
    }
  });

  test("throws for an unknown template name (fail fast)", () => {
    expect(() => loadTemplate("does_not_exist")).toThrow();
  });
});
