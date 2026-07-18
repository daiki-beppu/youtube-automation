import { describe, expectTypeOf, it } from "vitest";

import type {
  CompatibilityRequest,
  ProgressMessage,
  ProtocolMap,
  RunRequest,
} from "../lib/messaging";

describe("community-helper messaging contract", () => {
  it("types run, stop and progress across popup, background and content", () => {
    expectTypeOf<ProtocolMap["checkCompatibility"]>().parameters.toEqualTypeOf<
      [CompatibilityRequest]
    >();
    expectTypeOf<ProtocolMap["run"]>().parameters.toEqualTypeOf<[RunRequest]>();
    expectTypeOf<ProtocolMap["stop"]>().parameters.toEqualTypeOf<[]>();
    expectTypeOf<ProtocolMap["progress"]>().parameters.toEqualTypeOf<
      [ProgressMessage]
    >();
  });
});
