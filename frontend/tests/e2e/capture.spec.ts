import { mkdir } from "node:fs/promises";
import path from "node:path";
import { test, expect } from "@playwright/test";
import { ALL_ROUTES, installApiFixtures } from "./fixtures";

/** Same fixtures and dimensions on both revisions produce a useful before/after comparison. */
test("capture all product routes with identical fixture data", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const destination = path.resolve(
    process.cwd(),
    ".hallmark",
    process.env.OFFERPILOT_CAPTURE_BASELINE === "1" ? "before" : "after",
  );
  await mkdir(destination, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  await page.addInitScript(() => {
    localStorage.setItem("mantine-color-scheme-value", "light");
    localStorage.removeItem("offerpilot-sidebar-collapsed");
  });
  const state = await installApiFixtures(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const route of ALL_ROUTES) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page.locator("h1").first()).toBeVisible();
    await expect(
      page.getByRole("status", { name: "正在加载", exact: true }),
    ).toHaveCount(0);
    await page.screenshot({
      path: path.join(
        destination,
        `${route === "/" ? "home" : route.slice(1)}-1440.png`,
      ),
      fullPage: true,
      animations: "disabled",
    });
  }
  expect(errors).toEqual([]);
  expect(state.unhandled).toEqual([]);
});
