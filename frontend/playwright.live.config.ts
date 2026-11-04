import { defineConfig } from "@playwright/test";
import baseConfig from "./playwright.config";

export default defineConfig({
  ...baseConfig,
  testDir: "./tests/live",
  testMatch: "**/real.spec.ts",
  timeout: 120_000,
  outputDir: "test-results/live-artifacts",
  reporter: [
    ["list"],
    ["html", { outputFolder: "test-results/live-report", open: "never" }],
  ],
  use: {
    ...baseConfig.use,
    baseURL: process.env.OFFERPILOT_TEST_BASE_URL ?? "http://127.0.0.1:3101",
    viewport: { width: 1440, height: 1000 },
  },
});
