// distrokid.com/new モックに対する注入スモーク（要件 #11）。
//
// jsdom では検証できない 2 点を実 Chromium で固定する:
//   1. <input type=file> への DataTransfer 経由の File セット（要件 #6）
//   2. React 互換ネイティブ setter によるテキスト注入での change 発火（要件 #5）
// あわせて「続ける」ボタンが押されないこと（要件 #7）を担保する。
//
// ここで使う注入手法は lib/distrokid-injector.ts が実装すべき技法と同一。
// （実拡張ロードによる full E2E は #697 の WXT 基盤整備後のフォローアップ）

import { test, expect } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const fixtureUrl =
  "file://" + join(here, "fixtures", "distrokid-new.html");

test("テキスト・ファイル注入が成立し、送信ボタンは押されない", async ({ page }) => {
  // Given: モックフォームを開き、change イベントを監視する
  await page.goto(fixtureUrl);
  await page.evaluate(() => {
    (window as unknown as { __changed: string[] }).__changed = [];
    for (const el of Array.from(document.querySelectorAll("input"))) {
      el.addEventListener("change", () => {
        (window as unknown as { __changed: string[] }).__changed.push(
          el.getAttribute("name") ?? "",
        );
      });
    }
  });

  // When: テキストは prototype native setter、ファイルは DataTransfer で注入する
  await page.evaluate(() => {
    const setNativeValue = (el: HTMLInputElement, value: string) => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    };
    const artist = document.querySelector<HTMLInputElement>(
      'input[name="artist_name"]',
    )!;
    setNativeValue(artist, "City Nights");

    const songInput = document.querySelector<HTMLInputElement>(
      'input[name="song_file"]',
    )!;
    const file = new File(["audio-bytes"], "track-01.mp3", {
      type: "audio/mpeg",
    });
    const dt = new DataTransfer();
    dt.items.add(file);
    songInput.files = dt.files;
    songInput.dispatchEvent(new Event("change", { bubbles: true }));
  });

  // Then: テキスト値・ファイル名がセットされ change が両方で発火している
  await expect(page.locator('input[name="artist_name"]')).toHaveValue(
    "City Nights",
  );
  const songFileName = await page.evaluate(
    () =>
      document.querySelector<HTMLInputElement>('input[name="song_file"]')!
        .files?.[0]?.name,
  );
  expect(songFileName).toBe("track-01.mp3");

  const changed = await page.evaluate(
    () => (window as unknown as { __changed: string[] }).__changed,
  );
  expect(changed).toContain("artist_name");
  expect(changed).toContain("song_file");

  // Then: 送信系ボタンは拡張から押されない
  const continueClicked = await page.evaluate(
    () => (window as unknown as { __continueClicked: boolean }).__continueClicked,
  );
  expect(continueClicked).toBe(false);
});
