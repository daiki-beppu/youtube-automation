// Tests for the CLI-only interactive auth service's INTERNAL helpers
// (ADR-0003 §5). interactiveAuthService itself opens a browser + spins a local
// callback server, so an end-to-end test would need a real Google OAuth round
// trip (order.md: "interactiveAuthService は実 OAuth fixture 不可なので 内部関数
// の unit test に絞る"). We instead unit-test the decomposed helpers
// `buildAuthUrl` / `exchangeCode`, importing them from interactive-internal.ts
// by relative path because they are implementation internals, deliberately kept
// off the public oauth subpath.
//
// Seam contract (the helpers delegate to a google-auth-library OAuth2Client):
//   buildAuthUrl(client, scopes) -> client.generateAuthUrl({ access_type, scope })
//   exchangeCode(client, code)   -> (await client.getToken(code)).tokens

import { describe, expect, test } from "bun:test";

import {
  buildAuthUrl,
  exchangeCode,
} from "../src/oauth/interactive-internal.ts";
import * as interactiveModule from "../src/oauth/interactive.ts";

const scopes = [
  "https://www.googleapis.com/auth/youtube",
  "https://www.googleapis.com/auth/yt-analytics.readonly",
];

describe("buildAuthUrl", () => {
  test("requests offline access for every scope so a refresh_token is issued", () => {
    // Given a fake OAuth client capturing the generateAuthUrl options
    const captured: Record<string, unknown>[] = [];
    const client = {
      generateAuthUrl: (options: Record<string, unknown>) => {
        captured.push(options);
        return "https://accounts.google.com/o/oauth2/v2/auth?mock=1";
      },
    } as unknown as Parameters<typeof buildAuthUrl>[0];

    // When building the consent URL
    const url = buildAuthUrl(client, scopes);

    // Then the generated URL is returned verbatim ...
    expect(url).toBe("https://accounts.google.com/o/oauth2/v2/auth?mock=1");
    // ... offline access is requested (required to receive a refresh_token) ...
    expect(captured).toHaveLength(1);
    expect(captured[0]?.access_type).toBe("offline");
    // ... and every requested scope is forwarded to the client
    expect(JSON.stringify(captured[0])).toContain(
      "https://www.googleapis.com/auth/youtube"
    );
    expect(JSON.stringify(captured[0])).toContain(
      "https://www.googleapis.com/auth/yt-analytics.readonly"
    );
  });
});

describe("exchangeCode", () => {
  test("exchanges an authorization code for the issued credentials", async () => {
    // Given a fake OAuth client that returns tokens for a code
    const issued = {
      access_token: "issued-access",
      refresh_token: "issued-refresh",
    };
    const codes: string[] = [];
    const client = {
      getToken: (code: string) => {
        codes.push(code);
        return Promise.resolve({ tokens: issued });
      },
    } as unknown as Parameters<typeof exchangeCode>[0];

    // When exchanging the authorization code
    const tokens = await exchangeCode(client, "auth-code-123");

    // Then the issued credentials come back and the code was forwarded verbatim
    expect(tokens).toEqual(issued);
    expect(codes).toEqual(["auth-code-123"]);
  });

  test("propagates an exchange failure for the service boundary to convert", async () => {
    // Given a fake client whose token exchange rejects
    const client = {
      getToken: () =>
        Promise.reject(new Error("invalid_grant: bad verification code")),
    } as unknown as Parameters<typeof exchangeCode>[0];

    // When exchanging the code
    // Then the helper rejects; mapping to a ServiceError is the service's job
    await expect(exchangeCode(client, "bad-code")).rejects.toThrow(
      "invalid_grant"
    );
  });
});

// Guards the public oauth surface against re-leaking implementation internals
// (ADR-0003 §7 public-API minimization). The package.json subpath
// "@tayk/core/oauth/interactive" maps to interactive.ts, so this
// module's own exports ARE the public surface. buildAuthUrl / exchangeCode now
// live in interactive-internal.ts (relative-only); re-exporting them here would
// expose internals again.
describe("public oauth/interactive surface", () => {
  test("exposes interactiveAuthService only (no internal helpers leaked)", () => {
    // Given the module backing the public oauth/interactive subpath
    // When inspecting its exports
    // Then only the domain service is reachable, never the impl helpers
    expect(Object.keys(interactiveModule).toSorted()).toEqual([
      "interactiveAuthService",
    ]);
  });
});
