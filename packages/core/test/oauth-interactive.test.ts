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
//   buildAuthUrl(client, scopes, state) -> generateAuthUrl({ access_type, scope, state })
//   exchangeCode(client, code)   -> (await client.getToken(code)).tokens

import { describe, expect, test } from "bun:test";

import {
  OAUTH_STATE_MISMATCH_MESSAGE,
  buildAuthUrl,
  exchangeCode,
  generateOAuthState,
  parseOAuthCallback,
} from "../src/oauth/interactive-internal.ts";
import * as interactiveModule from "../src/oauth/interactive.ts";
import { interactiveAuthService } from "../src/oauth/interactive.ts";

const scopes = [
  "https://www.googleapis.com/auth/youtube",
  "https://www.googleapis.com/auth/yt-analytics.readonly",
];

describe("generateOAuthState", () => {
  test("returns a URL-safe unpadded 32-byte state token", () => {
    const state = generateOAuthState();

    expect(state).toHaveLength(43);
    expect(state).toMatch(/^[A-Za-z0-9_-]+$/u);
    expect(state).not.toContain("=");
  });
});

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
    const url = buildAuthUrl(client, scopes, "state-123");

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
    // ... and the CSRF state is attached for callback verification
    expect(captured[0]?.state).toBe("state-123");
  });
});

describe("parseOAuthCallback", () => {
  test("returns the code when callback state matches", () => {
    const result = parseOAuthCallback(
      new Request("http://localhost/?code=auth-code&state=expected-state"),
      "expected-state"
    );

    expect(result).toEqual({ code: "auth-code", status: "code" });
  });

  test("returns an auth error when state is missing", () => {
    const result = parseOAuthCallback(
      new Request("http://localhost/?code=auth-code"),
      "expected-state"
    );

    expect(result.status).toBe("error");
    if (result.status !== "error") {
      throw new Error("expected callback error");
    }
    expect(result.error.message).toBe(OAUTH_STATE_MISMATCH_MESSAGE);
  });

  test("returns an auth error when state is mismatched", () => {
    const result = parseOAuthCallback(
      new Request("http://localhost/?code=auth-code&state=attacker-state"),
      "expected-state"
    );

    expect(result.status).toBe("error");
    if (result.status !== "error") {
      throw new Error("expected callback error");
    }
    expect(result.error.message).toBe(OAUTH_STATE_MISMATCH_MESSAGE);
  });

  test("returns an auth error when consent is denied", () => {
    const result = parseOAuthCallback(
      new Request("http://localhost/?error=access_denied&state=expected-state"),
      "expected-state"
    );

    expect(result.status).toBe("error");
    if (result.status !== "error") {
      throw new Error("expected callback error");
    }
    expect(result.error.message).toBe("auth: consent denied: access_denied");
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

type InteractiveDeps = NonNullable<
  Parameters<typeof interactiveAuthService>[1]
>;
type InteractiveInput = Parameters<typeof interactiveAuthService>[0];

const clientSecretsJson = JSON.stringify({
  installed: {
    client_id: "cid.apps.googleusercontent.com",
    client_secret: "the-client-secret",
    redirect_uris: ["http://localhost"],
  },
});

const makeInteractiveDeps = (
  callbackState: "match" | "mismatch",
  exchangeBehavior: () => Promise<Record<string, unknown>>
) => {
  let fetchHandler:
    | ((request: Request) => Response | Promise<Response>)
    | undefined;
  const exchangedCodes: string[] = [];
  const openedUrls: string[] = [];
  const stopped: boolean[] = [];

  const deps: InteractiveDeps = {
    createOAuthClient: () =>
      ({
        generateAuthUrl: (options: {
          access_type: "offline";
          scope: string[];
          state: string;
        }) =>
          `https://accounts.google.com/mock?state=${encodeURIComponent(
            options.state
          )}`,
        getToken: () => Promise.reject(new Error("unused")),
      }) as ReturnType<InteractiveDeps["createOAuthClient"]>,
    exchangeCode: (_client, code) => {
      exchangedCodes.push(code);
      return exchangeBehavior() as ReturnType<InteractiveDeps["exchangeCode"]>;
    },
    generateState: () => "expected-state",
    openBrowser: (url) => {
      openedUrls.push(url);
      const state =
        callbackState === "match" ? "expected-state" : "attacker-state";
      if (!fetchHandler) {
        throw new Error("test setup: callback server was not started");
      }
      void fetchHandler(
        new Request(`http://localhost/?code=auth-code-123&state=${state}`)
      );
    },
    serve: (options) => {
      fetchHandler = options.fetch;
      return {
        port: 34_567,
        stop: (force: boolean) => {
          stopped.push(force);
        },
      };
    },
  };
  return { deps, exchangedCodes, openedUrls, stopped };
};

describe("interactiveAuthService boundary", () => {
  test("returns issued credentials as token.json when callback state matches", async () => {
    const { deps, exchangedCodes, openedUrls, stopped } = makeInteractiveDeps(
      "match",
      () =>
        Promise.resolve({
          access_token: "issued-access",
          refresh_token: "issued-refresh",
        })
    );

    const r = await interactiveAuthService({ clientSecretsJson, scopes }, deps);

    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(JSON.parse(r.value.tokenJson)).toEqual({
      access_token: "issued-access",
      refresh_token: "issued-refresh",
    });
    expect(openedUrls[0]).toContain("state=expected-state");
    expect(exchangedCodes).toEqual(["auth-code-123"]);
    expect(stopped).toEqual([true]);
  });

  test("returns an auth ServiceError when callback state mismatches", async () => {
    const { deps, exchangedCodes, stopped } = makeInteractiveDeps(
      "mismatch",
      () => Promise.resolve({ access_token: "unused" })
    );

    const r = await interactiveAuthService({ clientSecretsJson, scopes }, deps);

    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("auth");
    expect(r.error.message).toBe(OAUTH_STATE_MISMATCH_MESSAGE);
    expect(exchangedCodes).toEqual([]);
    expect(stopped).toEqual([true]);
  });

  test("maps code exchange failure to an auth ServiceError", async () => {
    const { deps, stopped } = makeInteractiveDeps("match", () =>
      Promise.reject(new Error("invalid_grant: bad verification code"))
    );

    const r = await interactiveAuthService({ clientSecretsJson, scopes }, deps);

    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("auth");
    expect(r.error.message).toContain("code exchange failed");
    expect(stopped).toEqual([true]);
  });

  test("rejects malformed input before starting the callback server", async () => {
    let serveCalls = 0;
    const { deps } = makeInteractiveDeps("match", () =>
      Promise.resolve({ access_token: "unused" })
    );
    const guardedDeps: InteractiveDeps = {
      ...deps,
      serve: (options) => {
        serveCalls += 1;
        return deps.serve(options);
      },
    };
    const malformed = {
      clientSecretsJson,
      scopes,
      unexpected: true,
    } as unknown as InteractiveInput;

    const r = await interactiveAuthService(malformed, guardedDeps);

    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected validation failure");
    }
    expect(r.error.domain).toBe("validation");
    expect(serveCalls).toBe(0);
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
    // Given the module backing the public oauth/interactive subpath
    // When inspecting its exports
    // Then only the domain service is reachable, never the impl helpers
    expect(Object.keys(interactiveModule).toSorted()).toEqual([
      "interactiveAuthService",
    ]);
  });
});
