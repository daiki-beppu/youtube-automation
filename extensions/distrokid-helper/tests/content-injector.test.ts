// @vitest-environment jsdom
//
// content script の document 束縛 injector の実配線テスト。
// helper 関数直叩きではなく createDocumentInjector(...).injectStaticFields() を通し、
// profile.artist が Apple Music credits まで届くことを固定する。

import { beforeEach, describe, expect, it } from "vitest";
import { createDocumentInjector } from "../lib/content-injector";
import type { DistrokidProfile, ReleasePayload } from "../lib/types";

const VISIBLE_RECT = {
  x: 0,
  y: 0,
  top: 0,
  left: 0,
  right: 100,
  bottom: 20,
  width: 100,
  height: 20,
  toJSON: () => ({}),
} as DOMRect;

const BASE_PROFILE: DistrokidProfile = {
  ai_disclosure: {
    apply_to_all: true,
    artist_persona: true,
    enabled: true,
    lyrics: true,
    music: true,
    partial_audio_type: null,
    recording_scope: "full",
  },
  artist: "ABYSS MI",
  credits: {
    performer_role: "Audio",
    producer_role: "Producer",
  },
  language: "English",
  main_genre: "Electronic",
  songwriter: null,
  sub_genre: "Ambient",
};

function makeVisible<T extends HTMLElement>(el: T): T {
  el.getBoundingClientRect = () => VISIBLE_RECT;
  return el;
}

function mountInput(attrs: {
  checked?: boolean;
  id?: string;
  name?: string;
  type?: string;
  value?: string;
}): HTMLInputElement {
  const input = document.createElement("input");
  if (attrs.id !== undefined) input.id = attrs.id;
  if (attrs.name !== undefined) input.name = attrs.name;
  if (attrs.type !== undefined) input.type = attrs.type;
  if (attrs.value !== undefined) {
    input.value = attrs.value;
    input.setAttribute("value", attrs.value);
  }
  if (attrs.checked !== undefined) input.checked = attrs.checked;
  document.body.appendChild(input);
  return makeVisible(input);
}

function mountSelect(id: string, values: string[]): HTMLSelectElement {
  const select = document.createElement("select");
  select.id = id;
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  }
  document.body.appendChild(select);
  return makeVisible(select);
}

function mountCreditRoleSelect(id: string, values: string[]): void {
  mountSelect(id, ["unselected", ...values]);
}

function mountStaticForm(trackCount: number, fallbackArtist: string): void {
  mountSelect("howManySongsOnThisAlbum", ["1", "2", "3"]);
  mountInput({ name: "previouslyReleased_0", type: "radio", value: "0", checked: true });
  mountInput({ name: "bandname" });
  mountSelect("language", ["English", "Japanese"]);
  mountSelect("genrePrimary", ["Electronic", "Jazz"]);
  mountSelect("genreSecondary", ["Ambient", "House"]);
  mountInput({ id: "albumTitleInput" });
  mountInput({ id: "release-date-dp", type: "date" });
  mountInput({ id: "artistName", type: "hidden", value: fallbackArtist });
  mountInput({ id: "chkapple", name: "store", type: "checkbox" });
  mountInput({ id: "chksnap", name: "store", type: "checkbox", checked: true });
  mountInput({ id: "areyousurepromoservices", type: "checkbox" });
  mountInput({ id: "areyousurerecorded", type: "checkbox" });
  mountInput({ id: "areyousureotherartist", type: "checkbox" });
  mountInput({ id: "areyousuretandc", type: "checkbox" });

  const trigger = document.createElement("div");
  trigger.className = "requirements-item-title";
  trigger.textContent = "クレジットを追加";
  document.body.appendChild(makeVisible(trigger));

  for (let i = 1; i <= trackCount; i += 1) {
    mountInput({ name: `title_${String.fromCharCode(96 + i)}` });
    mountInput({ id: `track-${i}-performer-1-name`, name: "performer-name" });
    mountCreditRoleSelect(`track-${i}-performer-1-role`, ["Audio", "Synthesizer"]);
    mountInput({ id: `track-${i}-producer-1-name`, name: "producer-name" });
    mountCreditRoleSelect(`track-${i}-producer-1-role`, ["Producer", "Executive producer"]);
  }
}

function payload(profile: DistrokidProfile): ReleasePayload {
  return {
    profile,
    release: {
      album_title: "Night Orbit",
      cover: null,
      release_date: "2026-07-01",
      tracks: [
        {
          asset_path: "/distrokid/assets/track-01.mp3",
          filename: "track-01.mp3",
          title: "Track 01",
        },
      ],
    },
  };
}

describe("createDocumentInjector", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("injectStaticFields が profile.artist を Apple Music credits へ渡す", async () => {
    // Given
    mountStaticForm(1, "Soulful Grooves");

    // When
    await createDocumentInjector(document).injectStaticFields(payload(BASE_PROFILE));

    // Then
    expect(document.querySelector<HTMLInputElement>('input[name="bandname"]')!.value).toBe("ABYSS MI");
    expect(document.querySelector<HTMLInputElement>("#track-1-performer-1-name")!.value).toBe("ABYSS MI");
    expect(document.querySelector<HTMLInputElement>("#track-1-producer-1-name")!.value).toBe("ABYSS MI");
  });

  it("profile.artist が空なら content 実配線でも #artistName fallback を使う", async () => {
    // Given
    mountStaticForm(1, "Soulful Grooves");

    // When
    await createDocumentInjector(document).injectStaticFields(
      payload({
        ...BASE_PROFILE,
        artist: "",
      }),
    );

    // Then
    expect(document.querySelector<HTMLInputElement>('input[name="bandname"]')!.value).toBe("");
    expect(document.querySelector<HTMLInputElement>("#track-1-performer-1-name")!.value).toBe("Soulful Grooves");
    expect(document.querySelector<HTMLInputElement>("#track-1-producer-1-name")!.value).toBe("Soulful Grooves");
  });
});
