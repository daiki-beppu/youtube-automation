import { describe, expect, test } from "bun:test";

import {
  readCoercedNumberCell,
  readNonEmptyStringCell,
  readNumberCell,
  readStringCell,
  requireHeaders,
  resolveColumnIndex,
} from "../src/analytics/column-helpers.ts";

const context = "analytics helper test";
const headers = [{ name: "day" }, { name: "views" }];

describe("analytics column helpers", () => {
  test("requires response column headers when rows are present", () => {
    expect(
      requireHeaders(
        { columnHeaders: headers, rows: [["2026-06-01"]] },
        context
      )
    ).toBe(headers);

    expect(() => requireHeaders({ rows: [["2026-06-01"]] }, context)).toThrow(
      `${context}: response has rows but no columnHeaders`
    );
  });

  test("resolves columns by header name and rejects missing columns", () => {
    expect(resolveColumnIndex(headers, "views", context)).toBe(1);

    expect(() => resolveColumnIndex(headers, "likes", context)).toThrow(
      `${context}: response is missing the "likes" column`
    );
  });

  test("reads string cells without imposing a non-empty contract", () => {
    expect(readStringCell(["YT_SEARCH"], 0, "source", context)).toBe(
      "YT_SEARCH"
    );
    expect(readStringCell([""], 0, "source", context)).toBe("");

    expect(() => readStringCell([42], 0, "source", context)).toThrow(
      `${context}: response has a non-string "source" value`
    );
  });

  test("reads non-empty string cells with the traffic-source error contract", () => {
    expect(readNonEmptyStringCell(["YT_SEARCH"], 0, "source", context)).toBe(
      "YT_SEARCH"
    );

    expect(() => readNonEmptyStringCell([42], 0, "source", context)).toThrow(
      `${context}: response has an invalid "source" value`
    );
    expect(() => readNonEmptyStringCell([""], 0, "source", context)).toThrow(
      `${context}: response has an invalid "source" value`
    );
  });

  test("reads finite numeric cells without coercion", () => {
    expect(readNumberCell([42], 0, "views", context)).toBe(42);

    expect(() => readNumberCell(["42"], 0, "views", context)).toThrow(
      `${context}: response has a non-numeric "views" value`
    );
    expect(() =>
      readNumberCell([Number.POSITIVE_INFINITY], 0, "views", context)
    ).toThrow(`${context}: response has a non-numeric "views" value`);
  });

  test("reads coerced finite numeric cells", () => {
    expect(readCoercedNumberCell(["42"], 0, "views", context)).toBe(42);
    expect(readCoercedNumberCell([7], 0, "views", context)).toBe(7);

    expect(() =>
      readCoercedNumberCell(["not-a-number"], 0, "views", context)
    ).toThrow(`${context}: response has a non-numeric "views" value`);
  });
});
