// Tests for the pure googleapis client factories (ADR-0003 §7).
//
// buildYouTubeClient / buildYouTubeAnalyticsClient turn a token.json string into
// a configured googleapis client WITHOUT any I/O or network round-trip. The
// acceptance criterion is purity: passing placeholder credentials still produces
// a usable client object (no auth happens at construction time). These tests feed
// a dummy Credentials-shaped token (ADR-0003: token.json is persisted in the Node
// google-auth-library Credentials shape — access_token / refresh_token /
// expiry_date) and assert the returned client exposes the expected API resource
// namespaces. They import via the package `exports` subpath so a missing
// `./oauth/client` entry fails resolution here, not silently at runtime.

import { describe, expect, test } from "bun:test";

import {
  buildYouTubeAnalyticsClient,
  buildYouTubeClient,
} from "@youtube-automation/core/oauth/client";

// A placeholder google-auth-library Credentials object. `expiry_date` sits in the
// year 2100 so nothing here is treated as expired; the factory must not care.
const dummyTokenJson = JSON.stringify({
  access_token: "ya29.placeholder",
  expiry_date: 4_102_444_800_000,
  refresh_token: "1//placeholder",
  scope: "https://www.googleapis.com/auth/youtube",
  token_type: "Bearer",
});

describe("buildYouTubeClient", () => {
  test("builds a youtube_v3 client from placeholder credentials without throwing", () => {
    // Given a Credentials-shaped token carrying only placeholder values
    // When building the Data API client
    const client = buildYouTubeClient(dummyTokenJson);

    // Then construction succeeds (pure factory) and exposes Data API resources
    expect(client).toBeDefined();
    expect(typeof client.videos).toBe("object");
    expect(typeof client.channels).toBe("object");
  });

  test("returns an independent client instance per call (no cached singleton)", () => {
    // Given the same token string
    // When building twice
    const first = buildYouTubeClient(dummyTokenJson);
    const second = buildYouTubeClient(dummyTokenJson);

    // Then each call yields its own instance — the factory holds no shared state
    expect(first).not.toBe(second);
  });

  test("throws on a token string that is not valid JSON (fail fast)", () => {
    // Given a malformed token string
    // When building the client
    // Then it fails fast rather than building a client with empty credentials
    expect(() => buildYouTubeClient("not-json")).toThrow();
  });
});

describe("buildYouTubeAnalyticsClient", () => {
  test("builds a youtubeAnalytics_v2 client from placeholder credentials", () => {
    // Given a Credentials-shaped token
    // When building the Analytics API client
    const client = buildYouTubeAnalyticsClient(dummyTokenJson);

    // Then construction succeeds and exposes the Analytics reports resource
    expect(client).toBeDefined();
    expect(typeof client.reports).toBe("object");
  });
});
