import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

const localChrome =
  "/home/ubuntu/.local/share/offerpilot-chrome/opt/google/chrome/chrome";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch:
    process.env.OFFERPILOT_CAPTURE_BASELINE === "1"
      ? "**/capture.spec.ts"
      : ["**/smoke.spec.ts", "**/capture.spec.ts"],
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: "test-results/artifacts",
  reporter: [
    ["list"],
    ["html", { outputFolder: "test-results/report", open: "never" }],
  ],
  use: {
    baseURL: process.env.OFFERPILOT_TEST_BASE_URL ?? "http://127.0.0.1:3101",
    browserName: "chromium",
    headless: true,
    launchOptions: {
      executablePath:
        process.env.OFFERPILOT_CHROME_PATH ??
        (existsSync(localChrome) ? localChrome : undefined),
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    },
    reducedMotion: "reduce",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
