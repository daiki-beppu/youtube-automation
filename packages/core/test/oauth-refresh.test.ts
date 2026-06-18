// Tests for refreshTokenService (ADR-0003 §5) — the PURE OAuth refresh service
// usable from both CLI and MCP (no browser, no local server).
//
// The service returns Promise<Result<{ tokenJson }, ServiceError>>: it never
// throws across its boundary and maps refresh failures to a ServiceError. The
// google-auth-library OAuth2Client is reached through an optional `deps` injection
// seam (mirroring the image service's deps pattern, image/service.ts:38-58 and
// image-gemini.test.ts:99) so these unit tests run with a fake client and never
// touch the network.
//
// Seam contract (documented here so the implementation matches the fakes):
//   deps.createOAuthClient({ clientId, clientSecret }) -> client
//   client.setCredentials(credentials)   // seeds the stored refresh_token
//   await client.refreshAccessToken()    // -> { credentials }
// The service extracts clientId / clientSecret from the client_secrets.json
// `installed` (or `web`) block, seeds the stored token, refreshes, and serializes
// the refreshed credentials back to a token.json string.

import { describe, expect, test } from "bun:test";

import { refreshTokenService } from "@tayk/core/oauth/refresh";

// Derive the deps bag type from the service itself (image-gemini.test.ts:38-40)
// so the test does not hard-code the injection shape's exported name.
type RefreshDeps = NonNullable<Parameters<typeof refreshTokenService>[1]>;
type RefreshInput = Parameters<typeof refreshTokenService>[0];

const clientSecretsJson = JSON.stringify({
  installed: {
    client_id: "cid.apps.googleusercontent.com",
    client_secret: "the-client-secret",
    redirect_uris: ["http://localhost"],
  },
});

// A stored token whose access token has long expired but still carries a usable
// refresh_token (the only field a refresh actually needs).
const expiredTokenJson = JSON.stringify({
  access_token: "old-access",
  expiry_date: 1000,
  refresh_token: "stored-refresh-token",
});

type RefreshBehavior = () => { credentials: Record<string, unknown> };

// A fake OAuth2Client recording the credentials it was seeded with and running
// the supplied behavior when refreshAccessToken is awaited.
const makeOAuthClient = (behavior: RefreshBehavior) => {
  const seeded: Record<string, unknown>[] = [];
  const client = {
    refreshAccessToken: () => Promise.resolve().then(behavior),
    setCredentials: (credentials: Record<string, unknown>) => {
      seeded.push(credentials);
    },
  };
  return { client, seeded };
};

// Wraps the fake client in the deps seam, recording the factory's config arg so
// the test can confirm the client_secrets credentials were extracted correctly.
const makeDeps = (client: unknown) => {
  const configs: unknown[] = [];
  const deps = {
    createOAuthClient: (config: unknown) => {
      configs.push(config);
      return client;
    },
  } as unknown as RefreshDeps;
  return { configs, deps };
};

describe("refreshTokenService success", () => {
  test("refreshes the stored token and returns the new credentials as token.json", async () => {
    // Given a fake OAuth client that yields a freshly refreshed access token
    const refreshed = {
      access_token: "new-access",
      expiry_date: 4_102_444_800_000,
      refresh_token: "stored-refresh-token",
    };
    const { client, seeded } = makeOAuthClient(() => ({
      credentials: refreshed,
    }));
    const { configs, deps } = makeDeps(client);

    // When refreshing the expired token
    const r = await refreshTokenService(
      { clientSecretsJson, tokenJson: expiredTokenJson },
      deps
    );

    // Then the result is ok and carries the refreshed credentials as a string
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    const out = JSON.parse(r.value.tokenJson) as { access_token?: string };
    expect(out.access_token).toBe("new-access");

    // And the client was seeded with the stored refresh_token before refreshing
    expect(seeded).toHaveLength(1);
    expect(JSON.stringify(seeded[0])).toContain("stored-refresh-token");

    // And the client factory received the parsed client_secrets credentials
    expect(JSON.stringify(configs[0])).toContain(
      "cid.apps.googleusercontent.com"
    );
    expect(JSON.stringify(configs[0])).toContain("the-client-secret");
  });
});

describe("refreshTokenService failure", () => {
  test("maps a refresh error to an auth ServiceError without throwing", async () => {
    // Given a fake OAuth client whose refresh rejects (e.g. a revoked grant)
    const { client } = makeOAuthClient(() => {
      throw new Error("invalid_grant: Token has been expired or revoked.");
    });
    const { deps } = makeDeps(client);

    // When refreshing
    const r = await refreshTokenService(
      { clientSecretsJson, tokenJson: expiredTokenJson },
      deps
    );

    // Then it returns err(domain "auth") — the boundary converts, never throws
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("auth");
  });
});

describe("refreshTokenService input validation", () => {
  test("rejects an unknown input key via the strict schema as a validation error", async () => {
    // Given a fake client that would succeed if it were ever reached
    const { client } = makeOAuthClient(() => ({
      credentials: { access_token: "x", expiry_date: 1 },
    }));
    const { deps } = makeDeps(client);

    // And an input carrying an extra key the `.strict()` schema must reject
    const malformed = {
      clientSecretsJson,
      tokenJson: expiredTokenJson,
      unexpected: true,
    } as unknown as RefreshInput;

    // When refreshing with the malformed input
    const r = await refreshTokenService(malformed, deps);

    // Then the boundary parses first and reports a validation ServiceError
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected validation failure");
    }
    expect(r.error.domain).toBe("validation");
  });
});
