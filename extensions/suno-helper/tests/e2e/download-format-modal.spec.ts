import { expect, test } from "@playwright/test";

test("Base UI の一意な可視形式 dialog で M4A 既定から MP3 を選び Download できる", async ({
  page,
}) => {
  await page.setContent(`
    <div role="dialog"><button>Cancel</button></div>
    <div role="dialog" hidden>
      <button>M4A</button><button>MP3</button><button>WAV</button><button>Download</button>
    </div>
    <div role="dialog" data-open data-base-ui-focusable>
      <button aria-pressed="true">M4A</button>
      <button aria-pressed="false">MP3</button>
      <button aria-pressed="false">WAV</button>
      <button>Download</button>
    </div>
    <script>
      const dialog = document.querySelector('[role="dialog"][data-open]');
      for (const button of dialog.querySelectorAll('button')) {
        button.addEventListener('click', () => {
          if (button.textContent === 'MP3') {
            for (const option of dialog.querySelectorAll('[aria-pressed]')) {
              option.setAttribute('aria-pressed', String(option === button));
            }
          }
          if (button.textContent === 'Download') dialog.remove();
        });
      }
    </script>
  `);

  const formatDialog = page
    .getByRole("dialog")
    .filter({ has: page.getByRole("button", { name: "M4A", exact: true }) })
    .filter({ has: page.getByRole("button", { name: "MP3", exact: true }) })
    .filter({ has: page.getByRole("button", { name: "WAV", exact: true }) })
    .filter({
      has: page.getByRole("button", { name: "Download", exact: true }),
    });

  await expect(formatDialog).toHaveCount(1);
  await expect(
    formatDialog.getByRole("button", { name: "M4A", exact: true })
  ).toHaveAttribute("aria-pressed", "true");

  await formatDialog.getByRole("button", { name: "MP3", exact: true }).click();
  await expect(
    formatDialog.getByRole("button", { name: "MP3", exact: true })
  ).toHaveAttribute("aria-pressed", "true");

  await formatDialog
    .getByRole("button", { name: "Download", exact: true })
    .click();
  await expect(formatDialog).toHaveCount(0);
});
