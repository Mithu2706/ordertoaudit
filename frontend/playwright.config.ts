import { defineConfig, devices } from "@playwright/test";

/**
 * Browser end-to-end tests: the benchmark steps 4-7 clicked through the real UI.
 *
 * Run against a FRESH instance seeded with SEED=scenario SCENARIO_UNTIL=3 (benchmark steps
 * 1-3 done), e.g. `docker compose down -v && docker compose up -d`, then:
 *
 *     $env:E2E_BASE_URL = "http://localhost:8000"; npm run e2e
 *
 * Uses the installed Google Chrome (channel "chrome"), so no browser download is needed.
 * Set E2E_BROWSER_CHANNEL=msedge for Microsoft Edge, or run `npx playwright install chromium`
 * and set it to "" for Playwright's own Chromium.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // the steps share one database and run in order
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{
    name: "browser",
    use: { ...devices["Desktop Chrome"], channel: (process.env.E2E_BROWSER_CHANNEL ?? "chrome") || undefined },
  }],
});
