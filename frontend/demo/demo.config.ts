import { defineConfig, devices } from "@playwright/test";

/**
 * Records the demo video: the whole demo script (docs/DEMO_SCRIPT.md) driven in a real browser,
 * with on-screen captions instead of narration.
 *
 * Needs a FRESH instance with benchmark steps 1-3 seeded (docker compose down -v; up -d) and
 * Playwright's encoder (`npx playwright install ffmpeg`, once). Then:
 *
 *     $env:E2E_BASE_URL = "http://localhost:8080"; npx playwright test -c demo/demo.config.ts
 *
 * The video is written to ../demo-video/ (git-ignored).
 */
export default defineConfig({
  testDir: ".",
  testMatch: "record-demo.ts",
  workers: 1,
  retries: 0,
  timeout: 20 * 60_000,
  reporter: [["list"]],
  outputDir: "../test-results/demo",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    viewport: { width: 1280, height: 720 },
    video: { mode: "on", size: { width: 1280, height: 720 } },
    launchOptions: { slowMo: 120 },
    actionTimeout: 15_000, // a stuck step fails fast instead of hanging the recording
  },
  projects: [{ name: "demo", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 720 },
    channel: (process.env.E2E_BROWSER_CHANNEL ?? "chrome") || undefined } }],
});
