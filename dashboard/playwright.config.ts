import { defineConfig } from "@playwright/test"

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  timeout: 30_000,
  use: {
    headless: true,
    trace: "retain-on-failure",
  },
})
