import { afterEach, beforeEach, describe, expect, test } from "bun:test";

import { migrateDistrokidService } from "@youtube-automation/core/distrokid-migrate";

import { Distrokid } from "../src/config/distrokid.ts";
import {
  cleanupDistrokidTargets,
  makeDistrokidTarget,
  oldDistrokid,
  readDistrokid,
  readProfile,
  writeDistrokid,
} from "./distrokid-migrate-fixtures.ts";
import type { JsonRecord } from "./distrokid-migrate-fixtures.ts";

let savedChannelDir: string | undefined;

beforeEach(() => {
  savedChannelDir = process.env.CHANNEL_DIR;
  Reflect.deleteProperty(process.env, "CHANNEL_DIR");
});

afterEach(() => {
  if (savedChannelDir === undefined) {
    Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  } else {
    process.env.CHANNEL_DIR = savedChannelDir;
  }
  cleanupDistrokidTargets();
});

const expectOk = async (
  input: Parameters<typeof migrateDistrokidService>[0]
): Promise<void> => {
  const result = await migrateDistrokidService(input);
  expect(result.ok).toBe(true);
};

describe("distrokid migrate service — profile conversion", () => {
  test("apply writes the nested songwriter and default ai_disclosure schema", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, oldDistrokid());

    await expectOk({ apply: true, backup: false, target });

    const profile = readProfile(target);
    expect(profile.language).toBe("ja");
    expect(profile.main_genre).toBe("Electronic");
    expect(profile.songwriter).toEqual({ first: "Jane", last: "Doe" });
    expect(profile.ai_disclosure).toEqual({
      apply_to_all: true,
      artist_persona: true,
      enabled: true,
      lyrics: true,
      music: true,
      partial_audio_type: null,
      recording_scope: "full",
    });
  });

  test("drops legacy flat profile fields from migration output", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, oldDistrokid());

    await expectOk({ apply: true, backup: false, target });

    const profile = readProfile(target);
    expect(profile).not.toHaveProperty("artist_name");
    expect(profile).not.toHaveProperty("apple_music_credit");
    expect(profile).not.toHaveProperty("track_type");
  });

  test("splits a single-word songwriter into first and blank last", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, oldDistrokid({}, { songwriter: "Jane" }));

    await expectOk({ apply: true, backup: false, target });

    expect(readProfile(target).songwriter).toEqual({ first: "Jane", last: "" });
  });

  test("splits middle songwriter tokens into the middle field", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, oldDistrokid({}, { songwriter: "Jane Quincy Doe" }));

    await expectOk({ apply: true, backup: false, target });

    expect(readProfile(target).songwriter).toEqual({
      first: "Jane",
      last: "Doe",
      middle: "Quincy",
    });
  });

  test("preserves known object songwriter fields for idempotency", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(
      target,
      oldDistrokid({}, { songwriter: { first: "Jane", last: "Doe" } })
    );

    await expectOk({ apply: true, backup: false, target });

    expect(readProfile(target).songwriter).toEqual({
      first: "Jane",
      last: "Doe",
    });
  });

  test("drops an empty songwriter string", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, oldDistrokid({}, { songwriter: "   " }));

    await expectOk({ apply: true, backup: false, target });

    expect(readProfile(target)).not.toHaveProperty("songwriter");
  });

  test("renames legacy ai_disclosure.composition to music", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(
      target,
      oldDistrokid(
        {},
        {
          ai_disclosure: {
            composition: false,
            enabled: true,
            lyrics: false,
            partial_audio_type: null,
          },
        }
      )
    );

    await expectOk({ apply: true, backup: false, target });

    const ai = readProfile(target).ai_disclosure as JsonRecord;
    expect(ai).not.toHaveProperty("composition");
    expect(ai.music).toBe(false);
    expect(ai.lyrics).toBe(false);
  });

  test("keeps explicit ai_disclosure.music over legacy composition", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(
      target,
      oldDistrokid({}, { ai_disclosure: { composition: false, music: true } })
    );

    await expectOk({ apply: true, backup: false, target });

    const ai = readProfile(target).ai_disclosure as JsonRecord;
    expect(ai.music).toBe(true);
    expect(ai).not.toHaveProperty("composition");
  });

  test("derives partial recording scope when partial_audio_type is present", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(
      target,
      oldDistrokid(
        {},
        { ai_disclosure: { composition: true, partial_audio_type: "vocals" } }
      )
    );

    await expectOk({ apply: true, backup: false, target });

    const ai = readProfile(target).ai_disclosure as JsonRecord;
    expect(ai.recording_scope).toBe("partial");
    expect(ai.partial_audio_type).toBe("vocals");
  });

  test("normalizes non-object ai_disclosure to the default disclosure schema", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, oldDistrokid({}, { ai_disclosure: false }));

    await expectOk({ apply: true, backup: false, target });

    expect(readProfile(target).ai_disclosure).toEqual({
      apply_to_all: true,
      artist_persona: true,
      enabled: true,
      lyrics: true,
      music: true,
      partial_audio_type: null,
      recording_scope: "full",
    });
  });

  test("keeps already-new schema destructive-field-free", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, {
      distrokid: {
        enabled: true,
        profile: {
          ai_disclosure: { music: true, recording_scope: "full" },
          language: "ja",
          main_genre: "Electronic",
          songwriter: { first: "Jane", last: "Doe" },
        },
      },
    });

    await expectOk({ apply: true, backup: false, target });

    const profile = readProfile(target);
    expect(profile.songwriter).toEqual({ first: "Jane", last: "Doe" });
    expect(profile.ai_disclosure as JsonRecord).not.toHaveProperty(
      "composition"
    );
    expect(profile).not.toHaveProperty("artist_name");
  });

  test("drops null songwriter during new schema remigration", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, {
      distrokid: {
        enabled: true,
        profile: {
          ai_disclosure: { music: true, recording_scope: "full" },
          language: "ja",
          main_genre: "Electronic",
          songwriter: null,
        },
      },
    });

    await expectOk({ apply: true, backup: false, target });

    const profile = readProfile(target);
    expect(profile).not.toHaveProperty("songwriter");
    expect(
      Distrokid.parse(readDistrokid(target)).profile.songwriter
    ).toBeNull();
  });

  test("remigrates new schema with omitted profile", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, {
      distrokid: {
        enabled: false,
      },
    });

    await expectOk({ apply: true, backup: false, target });

    expect(Distrokid.parse(readDistrokid(target)).profile).toEqual({
      aiDisclosure: {
        applyToAll: true,
        artistPersona: true,
        enabled: true,
        lyrics: true,
        music: true,
        partialAudioType: null,
        recordingScope: "full",
      },
      credits: {
        performerRole: "Synthesizer",
        producerRole: "Producer",
      },
      language: "",
      mainGenre: "",
      songwriter: null,
      subGenre: undefined,
    });
  });

  test("keeps migrated profile readable by the new config schema", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, {
      distrokid: {
        enabled: true,
        profile: {
          ai_disclosure: {
            music: true,
            recording_scope: "full",
            unexpected_ai_key: true,
          },
          credits: {
            performer_role: "Piano",
            producer_role: "Producer",
            unexpected_credit_key: true,
          },
          language: "ja",
          main_genre: "Electronic",
          songwriter: {
            first: "Jane",
            last: "Doe",
            unexpected_songwriter_key: true,
          },
          unexpected_profile_key: true,
        },
      },
    });

    await expectOk({ apply: true, backup: false, target });

    const profile = readProfile(target);
    expect(profile.songwriter).toEqual({ first: "Jane", last: "Doe" });
    expect(profile.songwriter as JsonRecord).not.toHaveProperty(
      "unexpected_songwriter_key"
    );
    expect(profile).not.toHaveProperty("unexpected_profile_key");
    expect(profile.ai_disclosure as JsonRecord).not.toHaveProperty(
      "unexpected_ai_key"
    );
    expect(profile.credits as JsonRecord).not.toHaveProperty(
      "unexpected_credit_key"
    );
    expect(Distrokid.parse(readDistrokid(target)).profile.songwriter).toEqual({
      first: "Jane",
      last: "Doe",
    });
  });

  test("returns a validation error for non-string and non-object songwriter", async () => {
    const target = makeDistrokidTarget();
    writeDistrokid(target, oldDistrokid({}, { songwriter: 42 }));

    const result = await migrateDistrokidService({
      apply: true,
      backup: false,
      target,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.message).toContain("songwriter");
    }
  });
});
