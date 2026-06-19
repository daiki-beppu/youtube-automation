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
//   buildAuthUrl(client, scopes, state) -> client.generateAuthUrl({ access_type, scope, state })
//   exchangeCode(client, code)   -> (await client.getToken(code)).tokens

import { describe, expect, test } from "bun:test";

import {
  buildAuthUrl,
  exchangeCode,
  generateOAuthState,
  resolveCallbackQuery,
} from "../src/oauth/interactive-internal.ts";
import * as interactiveModule from "../src/oauth/interactive.ts";

type InteractiveAuthDeps = NonNullable<
  Parameters<typeof interactiveModule.interactiveAuthService>[1]
>;
type InteractiveAuthInput = Parameters<
  typeof interactiveModule.interactiveAuthService
>[0];

const scopes = [
  "https://www.googleapis.com/auth/youtube",
  "https://www.googleapis.com/auth/yt-analytics.readonly",
];
const state = "state-123";
const clientSecretsJson = JSON.stringify({
  installed: {
    client_id: "cid.apps.googleusercontent.com",
    client_secret: "the-client-secret",
    redirect_uris: ["http://localhost"],
  },
});

describe("buildAuthUrl", () => {
  test("requests offline access and binds the consent URL to the issued state", () => {
    const captured: Record<string, unknown>[] = [];
    const client = {
      generateAuthUrl: (options: Record<string, unknown>) => {
        captured.push(options);
        return "https://accounts.google.com/o/oauth2/v2/auth?mock=1";
      },
    } as unknown as Parameters<typeof buildAuthUrl>[0];

    const url = buildAuthUrl(client, scopes, state);

    expect(url).toBe("https://accounts.google.com/o/oauth2/v2/auth?mock=1");
    expect(captured).toHaveLength(1);
    expect(captured[0]?.access_type).toBe("offline");
    expect(JSON.stringify(captured[0])).toContain(
      "https://www.googleapis.com/auth/youtube"
    );
    expect(JSON.stringify(captured[0])).toContain(
      "https://www.googleapis.com/auth/yt-analytics.readonly"
    );
    expect(captured[0]?.state).toBe(state);
  });
});

describe("OAuth callback state validation", () => {
  test("generates high-entropy callback state values", () => {
    const first = generateOAuthState();
    const second = generateOAuthState();

    expect(first).toMatch(/^[\w-]{43}$/u);
    expect(second).toMatch(/^[\w-]{43}$/u);
    expect(first).not.toBe(second);
  });

  test("accepts a code only when the callback state matches", () => {
    const query = new URLSearchParams({ code: "auth-code-123", state });

    const resolved = resolveCallbackQuery(query, state);

    expect(resolved).toEqual({ code: "auth-code-123", kind: "code" });
  });

  test("rejects missing state before accepting a callback code", () => {
    const query = new URLSearchParams({ code: "auth-code-123" });

    const resolved = resolveCallbackQuery(query, state);

    expect(resolved).toEqual({
      kind: "authError",
      message: "missing OAuth state",
    });
  });

  test("rejects mismatched state before accepting a callback code", () => {
    const query = new URLSearchParams({
      code: "attacker-code",
      state: "other-state",
    });

    const resolved = resolveCallbackQuery(query, state);

    expect(resolved).toEqual({
      kind: "authError",
      message: "OAuth state mismatch",
    });
  });

  test("maps consent denied callback errors to auth errors", () => {
    const query = new URLSearchParams({ error: "access_denied", state });

    const resolved = resolveCallbackQuery(query, state);

    expect(resolved).toEqual({
      kind: "authError",
      message: "consent denied: access_denied",
    });
  });

  test("keeps non-callback requests as 404 without auth side effects", () => {
    const query = new URLSearchParams({ ping: "1" });

    const resolved = resolveCallbackQuery(query, state);

    expect(resolved).toEqual({ kind: "notFound" });
  });
});

describe("exchangeCode", () => {
  test("exchanges an authorization code for the issued credentials", async () => {
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

    const tokens = await exchangeCode(client, "auth-code-123");

    expect(tokens).toEqual(issued);
    expect(codes).toEqual(["auth-code-123"]);
  });

  test("propagates an exchange failure for the service boundary to convert", async () => {
    const client = {
      getToken: () =>
        Promise.reject(new Error("invalid_grant: bad verification code")),
    } as unknown as Parameters<typeof exchangeCode>[0];

    await expect(exchangeCode(client, "bad-code")).rejects.toThrow(
      "invalid_grant"
    );
  });
});

const makeDeps = (
  runFlow: InteractiveAuthDeps["runFlow"]
): { calls: unknown[]; deps: InteractiveAuthDeps } => {
  const calls: unknown[] = [];
  const deps = {
    runFlow: (secrets: string, requestedScopes: string[]) => {
      calls.push({ requestedScopes, secrets });
      return runFlow(secrets, requestedScopes);
    },
  };
  return { calls, deps };
};

describe("interactiveAuthService boundary", () => {
  test("rejects unknown input keys before running the interactive flow", async () => {
    const { calls, deps } = makeDeps(() =>
      Promise.resolve(JSON.stringify({ access_token: "issued-access" }))
    );
    const malformed = {
      clientSecretsJson,
      scopes,
      unexpected: true,
    } as unknown as InteractiveAuthInput;

    const result = await interactiveModule.interactiveAuthService(
      malformed,
      deps
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation failure");
    }
    expect(result.error.domain).toBe("validation");
    expect(calls).toHaveLength(0);
  });

  test("returns tokenJson from the injected interactive flow", async () => {
    const tokenJson = JSON.stringify({ access_token: "issued-access" });
    const { calls, deps } = makeDeps(() => Promise.resolve(tokenJson));

    const result = await interactiveModule.interactiveAuthService(
      { clientSecretsJson, scopes },
      deps
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(
        `expected ok, got ${result.error.domain}: ${result.error.message}`
      );
    }
    expect(result.value.tokenJson).toBe(tokenJson);
    expect(calls).toHaveLength(1);
    expect(JSON.stringify(calls[0])).toContain(
      "cid.apps.googleusercontent.com"
    );
    expect(JSON.stringify(calls[0])).toContain(
      "https://www.googleapis.com/auth/youtube"
    );
  });

  test("maps interactive flow failures to a ServiceError without throwing", async () => {
    const { deps } = makeDeps(() =>
      Promise.reject(new Error("auth: token exchange failed: invalid_grant"))
    );

    const result = await interactiveModule.interactiveAuthService(
      { clientSecretsJson, scopes },
      deps
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected auth failure");
    }
    expect(result.error.domain).toBe("auth");
  });
});

// Guards the public oauth surface against re-leaking implementation internals
// (ADR-0003 §7 public-API minimization). The package.json subpath
// "@youtube-automation/core/oauth/interactive" maps to interactive.ts, so this
// module's own exports ARE the public surface. buildAuthUrl / exchangeCode now
// live in interactive-internal.ts (relative-only); re-exporting them here would
// expose internals again.
describe("public oauth/interactive surface", () => {
  test("exposes interactiveAuthService only (no internal helpers leaked)", () => {
    expect(Object.keys(interactiveModule).toSorted()).toEqual([
      "interactiveAuthService",
    ]);
  });
});
