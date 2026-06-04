// #854: 生成完了後の clip 一括 playlist 追加フロー (Cmd+P) の E2E スモーク (実 Suno 非依存)。
//
// content script は manifest の matches (`https://suno.com/*`) でしか注入されず、Playwright の
// page.evaluate に渡す関数はシリアライズされブラウザ文脈で実行されるため本番 `shared/playlist-dom.ts`
// を直接 import できない (既存 suno-queue.spec.ts と同じ制約)。よってここでは
// selectRecentCompletedClips / multiSelectClips / openAddToPlaylistDialogViaCmdP /
// fillPlaylistNameAndCreate / waitForPlaylistDialogClose と同手法を inline 再現し、
// 「完了 clip を multi-select → Cmd+P で dialog → 名前入力 → Create → dialog 消滅」が実ブラウザの
// layout 上で成立することを示す。本番関数の回帰は jsdom unit (tests/dom-playlist.test.ts) が担う。
import { expect, test } from "@playwright/test";

// Create 画面の mock。
//   - 完了 clip-row 4 件 (= 2 entry × 2 clip) + streaming 2 件（選択対象外）
//   - 各 clip-row は `.multi-select-button > button[aria-label="Select clip"]`
//   - OneTrust cookie dialog (role=dialog, aria-label="Privacy Preference Center", id="ot-...") が常駐し、
//     contrived に "Add to Playlist" テキストを含む（除外フィルタの検証用）
//   - Cmd+P で #playlist-dialog (初期 display:none) が開く。Create Playlist click で閉じる
const MOCK_HTML = `<!doctype html>
<html>
  <body>
    <div id="grid">
      ${Array.from({ length: 4 })
        .map(
          (_, i) =>
            `<div data-testid="clip-row" data-clip-status="complete" id="done-${i}" style="width:200px;height:60px">` +
            `<div class="multi-select-button"><button aria-label="Select clip" style="width:20px;height:20px"></button></div>` +
            `</div>`,
        )
        .join("\n")}
      ${Array.from({ length: 2 })
        .map(
          (_, i) =>
            `<div data-testid="clip-row" data-clip-status="streaming" id="streaming-${i}" style="width:200px;height:60px">` +
            `<div class="multi-select-button"><button aria-label="Select clip" style="width:20px;height:20px"></button></div>` +
            `</div>`,
        )
        .join("\n")}
    </div>

    <div id="ot-sdk-container" role="dialog" aria-label="Privacy Preference Center" style="width:360px;height:200px">
      <span>Add to Playlist (cookie consent noise)</span>
    </div>

    <div id="playlist-dialog" role="dialog" aria-modal="true" style="display:none;width:400px;height:300px">
      <span>Add to Playlist</span>
      <input placeholder="Playlist Name" type="text" style="width:200px;height:30px" />
      <button id="liked" style="width:120px;height:30px">Liked Songs</button>
      <button id="create" style="width:120px;height:30px">Create Playlist</button>
    </div>

    <script>
      // 各 Select clip ボタン: click で aria-label を Deselect clip に切替（実 Suno の選択トグル相当）。
      document.querySelectorAll('.multi-select-button > button').forEach((b) => {
        b.addEventListener('click', () => b.setAttribute('aria-label', 'Deselect clip'));
      });
      // Cmd/Ctrl+P: Add to Playlist dialog を開く。
      document.addEventListener('keydown', (e) => {
        if (e.key === 'p' && (e.metaKey || e.ctrlKey)) {
          document.getElementById('playlist-dialog').style.display = 'block';
        }
      });
      // Create Playlist: dialog を閉じる（playlist 作成完了相当）。
      document.getElementById('create').addEventListener('click', () => {
        document.getElementById('playlist-dialog').remove();
      });
    </script>
  </body>
</html>`;

test("完了 clip を multi-select し Cmd+P → 名前入力 → Create Playlist → dialog 消滅 (#854)", async ({ page }) => {
  await page.setContent(MOCK_HTML);

  const result = await page.evaluate(async () => {
    // --- 本番 shared/playlist-dom.ts と同手法を inline 再現 ---
    const isVisible = (el: HTMLElement): boolean => {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false;
      let node: HTMLElement | null = el;
      while (node) {
        const style = getComputedStyle(node);
        if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
          return false;
        }
        node = node.parentElement;
      }
      return true;
    };
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

    const selectRecentCompletedClips = (count: number): HTMLElement[] =>
      Array.from(document.querySelectorAll<HTMLElement>('[data-testid="clip-row"][data-clip-status="complete"]'))
        .filter(isVisible)
        .slice(0, count);

    const multiSelectClips = async (rows: HTMLElement[]): Promise<void> => {
      for (const row of rows) {
        row.querySelector<HTMLButtonElement>('.multi-select-button > button[aria-label="Select clip"]')?.click();
      }
    };

    // cookie 除外フィルタ込みの Add to Playlist dialog 判定。
    const findPlaylistDialog = (): HTMLElement | null =>
      Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]')).find((d) => {
        if (!isVisible(d)) return false;
        if (d.id.startsWith("ot-")) return false;
        if (/privacy/i.test(d.getAttribute("aria-label") ?? "")) return false;
        return (d.textContent ?? "").includes("Add to Playlist");
      }) ?? null;

    const openAddToPlaylistDialogViaCmdP = async (): Promise<HTMLElement> => {
      const isMac = navigator.platform.toLowerCase().includes("mac");
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "p", metaKey: isMac, ctrlKey: !isMac, bubbles: true }),
      );
      const deadline = Date.now() + 2000;
      while (Date.now() < deadline) {
        const dialog = findPlaylistDialog();
        if (dialog) return dialog;
        await sleep(20);
      }
      throw new Error("Add to Playlist dialog を検出できませんでした。");
    };

    const fillPlaylistNameAndCreate = async (dialog: HTMLElement, name: string): Promise<void> => {
      const input = dialog.querySelector<HTMLInputElement>('input[placeholder="Playlist Name"]');
      if (!input) throw new Error("Playlist Name input が見つかりません。");
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(input, name);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      const create = Array.from(dialog.querySelectorAll<HTMLButtonElement>("button")).find((b) =>
        (b.textContent ?? "").toLowerCase().includes("create playlist"),
      );
      if (!create) throw new Error("Create Playlist ボタンが見つかりません。");
      create.click();
    };

    const waitForPlaylistDialogClose = async (): Promise<void> => {
      const deadline = Date.now() + 2000;
      while (Date.now() < deadline) {
        if (!findPlaylistDialog()) return;
        await sleep(20);
      }
      throw new Error("dialog が閉じませんでした。");
    };

    // --- フロー実行 ---
    const rows = selectRecentCompletedClips(40);
    await multiSelectClips(rows);
    const selectedCount = document.querySelectorAll('.multi-select-button > button[aria-label="Deselect clip"]').length;

    const dialog = await openAddToPlaylistDialogViaCmdP();
    const dialogIsReal = dialog.id === "playlist-dialog";
    const cookieStillPresent = document.getElementById("ot-sdk-container") !== null;

    await fillPlaylistNameAndCreate(dialog, "rjn-dawn-cloud-fold");
    const inputValue = dialog.querySelector<HTMLInputElement>('input[placeholder="Playlist Name"]')?.value ?? "";

    await waitForPlaylistDialogClose();
    const dialogClosed = document.getElementById("playlist-dialog") === null;

    return {
      completedRowCount: rows.length,
      selectedCount,
      dialogIsReal,
      cookieExcluded: dialogIsReal && cookieStillPresent,
      inputValue,
      dialogClosed,
    };
  });

  expect(result.completedRowCount).toBe(4); // 完了 4 件のみ（streaming は対象外）
  expect(result.selectedCount).toBe(4); // 4 件すべて multi-select された
  expect(result.dialogIsReal).toBe(true); // cookie ではなく実 dialog を開いた
  expect(result.cookieExcluded).toBe(true); // cookie dialog は残存するが拾われていない
  expect(result.inputValue).toBe("rjn-dawn-cloud-fold"); // playlist 名が注入された
  expect(result.dialogClosed).toBe(true); // Create で dialog が消えた（完了検知）
});
