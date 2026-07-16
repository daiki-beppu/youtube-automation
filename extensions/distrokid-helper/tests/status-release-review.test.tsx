// @vitest-environment jsdom

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ReleaseReview } from "@/components/ReleaseReview";
import { StatusBanner } from "@/components/StatusBanner";
import { PHASES, type Phase } from "@/lib/messaging";
import type { ReleasePayload } from "@/lib/types";

const payload: ReleasePayload = {
  profile: {
    artist: "Midnight Echoes",
    language: "Japanese",
    main_genre: "Electronic",
    sub_genre: null,
    songwriter: null,
    ai_disclosure: {
      enabled: false,
      lyrics: false,
      music: false,
      recording_scope: "full",
      partial_audio_type: null,
      artist_persona: false,
      apply_to_all: true,
    },
    credits: { performer_role: "Synthesizer", producer_role: "Producer" },
  },
  release: {
    album_title: "Neon Skyline",
    tracks: [
      { title: "First Light", filename: "01-first-light.mp3", asset_path: "/distrokid/assets/01-first-light.mp3" },
      { title: "Night Drive", filename: "02-night-drive.mp3", asset_path: "/distrokid/assets/02-night-drive.mp3" },
    ],
    cover: { filename: "cover.jpg", asset_path: "/distrokid/assets/cover.jpg" },
    release_date: "2026-08-01",
  },
};

function parseMarkup(markup: string): HTMLElement {
  const container = document.createElement("div");
  container.innerHTML = markup;
  return container;
}

describe("StatusBanner", () => {
  const cases: ReadonlyArray<[Phase, string, string]> = [
    [PHASES.INJECTING, "フォームへ入力しています", "bg-blue-50"],
    [PHASES.DONE, "入力が完了しました", "bg-green-50"],
    [PHASES.ERROR, "入力に失敗しました", "bg-red-50"],
    [PHASES.STOPPED, "入力を停止しました", "bg-yellow-50"],
  ];

  it.each(cases)("%s phase は message と意味を表す role・配色を維持する", (phase, message, colorClass) => {
    const container = parseMarkup(renderToStaticMarkup(<StatusBanner phase={phase} message={message} />));
    const banner = container.firstElementChild;

    expect(banner?.textContent).toBe(message);
    expect(banner?.getAttribute("role")).toBe(phase === PHASES.ERROR ? "alert" : "status");
    expect(banner?.classList.contains(colorClass)).toBe(true);
    expect(banner?.getAttribute("data-slot")).toBe("alert");
    expect(banner?.querySelector('[data-slot="alert-description"]')?.textContent).toBe(message);
  });

  it("phase が null なら表示しない", () => {
    expect(renderToStaticMarkup(<StatusBanner phase={null} message="表示しない" />)).toBe("");
  });
});

describe("ReleaseReview", () => {
  it("Card 内に release metadata のラベルと値を表示する", () => {
    const container = parseMarkup(renderToStaticMarkup(<ReleaseReview payload={payload} />));
    const card = container.querySelector('[data-slot="card"]');
    const metadata = card?.querySelector("dl");

    expect(card?.querySelector('[data-slot="card-title"]')?.textContent).toBe("Neon Skyline");
    expect(card?.querySelector('[data-slot="card-content"]')).not.toBeNull();
    expect(Array.from(metadata?.querySelectorAll("dt") ?? [], (item) => item.textContent)).toEqual([
      "言語",
      "ジャンル",
      "リリース日",
      "曲数",
      "ジャケット",
    ]);
    expect(Array.from(metadata?.querySelectorAll("dd") ?? [], (item) => item.textContent)).toEqual([
      "Japanese",
      "Electronic",
      "2026-08-01",
      "2",
      "cover.jpg",
    ]);
  });

  it("未確定の release date と cover は従来の fallback を表示する", () => {
    const fallbackPayload: ReleasePayload = {
      ...payload,
      release: { ...payload.release, release_date: null, cover: null },
    };
    const container = parseMarkup(renderToStaticMarkup(<ReleaseReview payload={fallbackPayload} />));
    const values = Array.from(container.querySelectorAll("dd"), (item) => item.textContent);

    expect(values).toContain("未定");
    expect(values).toContain("なし");
  });
});
