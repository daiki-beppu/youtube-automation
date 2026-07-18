import { describe, expect, it } from "vitest";

import {
  acquireUnattendedLease,
  releaseUnattendedLease,
  renewUnattendedLease,
  UNATTENDED_LEASE_TTL_MS,
} from "../lib/unattended-lease";

describe("unattended collection lease", () => {
  it("rejects a second tab until the active lease expires", () => {
    const first = acquireUnattendedLease(
      {},
      { collectionId: "collection", requestId: "one", tabId: 1 },
      1000,
      "token-one"
    );
    expect(first.acquired).toBe(true);
    expect(
      acquireUnattendedLease(
        first.leases,
        { collectionId: "collection", requestId: "two", tabId: 2 },
        1001,
        "token-two"
      ).acquired
    ).toBe(false);
    expect(
      acquireUnattendedLease(
        first.leases,
        { collectionId: "other-collection", requestId: "three", tabId: 3 },
        1001,
        "token-three"
      ).acquired
    ).toBe(false);
    expect(
      acquireUnattendedLease(
        first.leases,
        { collectionId: "collection", requestId: "two", tabId: 2 },
        1000 + UNATTENDED_LEASE_TTL_MS,
        "token-two"
      ).acquired
    ).toBe(true);
  });

  it("only lets the owning token renew or release", () => {
    const acquired = acquireUnattendedLease(
      {},
      { collectionId: "collection", requestId: "one", tabId: 1 },
      1000,
      "owner"
    );
    expect(
      renewUnattendedLease(acquired.leases, "collection", "other", 2000)
    ).toBe(acquired.leases);
    expect(releaseUnattendedLease(acquired.leases, "collection", "other")).toBe(
      acquired.leases
    );
    expect(
      releaseUnattendedLease(acquired.leases, "collection", "owner")
    ).toEqual({});
  });
});
