import { defineConfig, devices } from "@playwright/test";

// distrokid.com/new モック（file://）に対する注入スモーク（要件 #11）。
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  reporter: "list",
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
