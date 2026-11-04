import { Buffer } from "node:buffer";
import { test, expect, type Page, type Route } from "@playwright/test";
import { ALL_ROUTES, JOB_ID, installApi } from "./fixtures";

async function settle(page: Page) {
  await expect(page.locator("h1").first()).toBeVisible();
  await expect(
    page.getByRole("status", { name: "正在加载", exact: true }),
  ).toHaveCount(0);
}

for (const viewport of [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 375, height: 812 },
]) {
  for (const theme of ["light", "dark"] as const) {
    test(`all 13 routes: ${viewport.name}, ${theme}, no runtime errors or horizontal overflow`, async ({
      page,
    }, testInfo) => {
      test.setTimeout(120_000);
      await page.setViewportSize(viewport);
      await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
      await page.addInitScript(
        (scheme) => localStorage.setItem("mantine-color-scheme-value", scheme),
        theme,
      );
      const state = await installApi(page);
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      for (const route of ALL_ROUTES) {
        await page.goto(route, { waitUntil: "domcontentloaded" });
        await settle(page);
        await expect(page.locator("html")).toHaveAttribute(
          "data-mantine-color-scheme",
          theme,
        );
        const dimensions = await page.evaluate(() => ({
          content: document.documentElement.scrollWidth,
          viewport: window.innerWidth,
        }));
        expect(
          dimensions.content,
          `${route} overflow at ${viewport.name}/${theme}`,
        ).toBeLessThanOrEqual(dimensions.viewport + 1);
        if (route === "/jobs" && viewport.name === "mobile") {
          const card = page.locator(".job-card").first();
          const title = await card.getByRole("heading", { level: 3 }).boundingBox();
          const stage = await card.getByRole("textbox", { name: "投递阶段", exact: true }).boundingBox();
          expect(title, "mobile job title remains visible").not.toBeNull();
          expect(title!.width, "stage controls must leave a readable title width").toBeGreaterThan(180);
          expect(stage!.y, "mobile stage controls belong below the title").toBeGreaterThan(title!.y + title!.height);
        }
        if (route === "/dashboard") {
          const contrast = await page
            .getByRole("link", { name: "管理岗位", exact: true })
            .evaluate((element) => {
              const style = getComputedStyle(element);
              const luminance = (color: string) => {
                const channels = color
                  .match(/[\d.]+/g)!
                  .slice(0, 3)
                  .map(Number)
                  .map((channel) => {
                    const value = channel / 255;
                    return value <= 0.04045
                      ? value / 12.92
                      : ((value + 0.055) / 1.055) ** 2.4;
                  });
                return (
                  channels[0] * 0.2126 +
                  channels[1] * 0.7152 +
                  channels[2] * 0.0722
                );
              };
              const foreground = luminance(style.color);
              const background = luminance(style.backgroundColor);
              return (
                (Math.max(foreground, background) + 0.05) /
                (Math.min(foreground, background) + 0.05)
              );
            });
          expect(
            contrast,
            `${theme} primary action text contrast`,
          ).toBeGreaterThanOrEqual(4.5);
        }
        await page.screenshot({
          path: testInfo.outputPath(
            `${route === "/" ? "home" : route.slice(1)}-${theme}-${viewport.name}.png`,
          ),
          fullPage: true,
          animations: "disabled",
        });
        expect(errors, `${route} page errors`).toEqual([]);
      }
      expect(state.unhandled).toEqual([]);
    });
  }
}

test("sidebar preference, keyboard quick jump and theme are persistent", async ({
  page,
}) => {
  await installApi(page);
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "折叠侧栏", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "展开侧栏", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "展开侧栏", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await page
    .getByPlaceholder("跳转到岗位、资料或 Agent 工作区…")
    .fill("资料问答");
  await page.getByRole("dialog").getByText("资料问答", { exact: true }).click();
  await expect(page).toHaveURL(/\/knowledge$/);
  await page.getByRole("button", { name: "切换主题", exact: true }).click();
  await page.getByRole("menuitem", { name: "深色", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute(
    "data-mantine-color-scheme",
    "dark",
  );
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute(
    "data-mantine-color-scheme",
    "dark",
  );
});

test("mobile drawer navigates and returns focus after dismissal", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await installApi(page);
  await page.goto("/dashboard");
  const trigger = page.getByRole("button", {
    name: "打开导航菜单",
    exact: true,
  });
  await trigger.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page
    .getByRole("dialog")
    .getByRole("link", { name: "岗位管理", exact: true })
    .click();
  await expect(page).toHaveURL(/\/jobs$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("jobs create and edit in place, then filter and reset", async ({
  page,
}) => {
  const state = await installApi(page);
  await page.goto("/jobs");
  await page.getByRole("button", { name: "添加岗位", exact: true }).click();
  await page.getByRole("menuitem", { name: "新增岗位", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("公司名称", { exact: true }).fill("测试工作室");
  await dialog.getByLabel("职位名称", { exact: true }).fill("前端实习生");
  await dialog.getByRole("button", { name: "保存岗位", exact: true }).click();
  const card = page.getByRole("article", {
    name: "测试工作室 前端实习生",
    exact: true,
  });
  await expect(card).toBeVisible();
  await expect(page.locator(".job-card").first()).toHaveAttribute(
    "aria-label",
    "测试工作室 前端实习生",
  );
  await expect(card).toBeInViewport();
  await card.getByRole("button", { name: "编辑", exact: true }).click();
  await card.getByLabel("职位名称", { exact: true }).fill("前端开发实习生");
  await card.getByRole("button", { name: "保存修改", exact: true }).click();
  await expect(
    page.getByRole("article", {
      name: "测试工作室 前端开发实习生",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByLabel("公司 / 职位 / 行业", { exact: true })
    .fill("no-such-company");
  await page.getByRole("button", { name: "筛选", exact: true }).click();
  await expect(
    page.getByText("没有符合条件的岗位", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "重置筛选", exact: true }).click();
  await expect(page.locator(".job-card")).toHaveCount(2);
  expect(
    state.calls.some(
      (call) => call.method === "PUT" && call.path.startsWith("/jobs/"),
    ),
  ).toBeTruthy();
});

test("CSV file preview keeps a selected row before importing it", async ({
  page,
}) => {
  const state = await installApi(page);
  await page.goto("/jobs");
  await page.getByRole("button", { name: "添加岗位", exact: true }).click();
  await page.getByRole("menuitem", { name: "导入 CSV", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "jobs.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("company_name,title\n星河科技,CSV 导入岗位\n"),
  });
  await dialog.getByRole("button", { name: "预览并检查", exact: true }).click();
  await expect(dialog.getByRole("table")).toBeVisible();
  await expect(
    dialog.getByRole("checkbox", { name: "选择 CSV 第 2 行", exact: true }),
  ).toBeChecked();
  await dialog
    .getByRole("button", { name: "导入选中的 1 条", exact: true })
    .click();
  await expect(
    page.getByRole("article", { name: "星河科技 CSV 导入岗位", exact: true }),
  ).toBeInViewport();
  expect(
    state.calls.filter(
      (call) => call.path === "/jobs/import" && call.method === "POST",
    ),
  ).toHaveLength(1);
});

test("AI confirmed job appears first immediately and survives refresh", async ({
  page,
}) => {
  const state = await installApi(page);
  await page.goto("/jobs?task=extract");
  await expect(
    page.getByRole("heading", { name: "提取完成，请核对", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator("label.agent-field")
      .filter({ hasText: "职位" })
      .locator("input"),
  ).toHaveValue("AI 导入岗位");
  await page
    .getByRole("button", { name: "确认并保存岗位", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".job-card").first()).toHaveAttribute(
    "aria-label",
    "星河科技 AI 导入岗位",
  );
  await expect(
    page.getByRole("article", { name: "星河科技 AI 导入岗位", exact: true }),
  ).toBeInViewport();
  await page.goto("/jobs");
  await expect(
    page.getByRole("article", { name: "星河科技 AI 导入岗位", exact: true }),
  ).toBeVisible();
  expect(
    state.calls.filter((call) => call.path === "/agent/job-extractions"),
  ).toHaveLength(0);
});

test("failed extraction can retry and a running extraction can cancel", async ({
  page,
}) => {
  const state = await installApi(page, { extractionStatus: "failed" });
  await page.goto("/jobs?task=extract");
  await expect(
    page.getByRole("heading", { name: "提取失败", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "提取完成，请核对", exact: true }),
  ).toBeVisible();
  state.extraction.status = "running";
  state.extraction.result = null;
  await page.reload();
  await page.getByRole("button", { name: "取消解析", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "任务已取消", exact: true }),
  ).toBeVisible();
});

test("profile saves and resume upload waits for explicit confirmation", async ({
  page,
}) => {
  const state = await installApi(page);
  await page.goto("/profile");
  await page.getByLabel("专业", { exact: true }).fill("软件工程");
  await page.getByRole("button", { name: "保存档案", exact: true }).click();
  await expect.poll(() => state.profile.major).toBe("软件工程");
  await page.getByRole("tab", { name: /简历版本/ }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "upload.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from(
      "%PDF-1.4\nfixture file; parsed text is supplied by the controlled API mock",
    ),
  });
  const preview = page.getByRole("dialog", {
    name: "简历解析预览",
    exact: true,
  });
  await expect(preview).toBeVisible();
  expect(
    state.calls.filter(
      (call) =>
        call.path.endsWith("/confirm") && call.path.startsWith("/resumes/"),
    ),
  ).toHaveLength(0);
  await preview
    .getByRole("button", { name: "确认这份简历", exact: true })
    .click();
  await expect(
    preview.getByText("已由你确认，可用于后续匹配。", { exact: true }),
  ).toBeVisible();
  expect(
    state.calls.filter((call) => call.path === "/resumes/upload"),
  ).toHaveLength(1);
});

test("personal RAG index and answer display source quotes", async ({
  page,
}) => {
  const state = await installApi(page);
  await page.goto("/knowledge");
  await page
    .getByRole("button", { name: "建立 / 更新索引", exact: true })
    .click();
  await expect(page.getByText("4 个片段", { exact: true })).toBeVisible();
  await page
    .getByRole("textbox", { name: "问题", exact: true })
    .fill("我的项目使用了哪些技术？");
  await page.getByRole("button", { name: "查询资料", exact: true }).click();
  await expect(
    page.getByText("你的项目经历包含 Python 和 SQL 实践。", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("引用资料", { exact: true })).toBeVisible();
  expect(
    state.calls.filter((call) => call.path === "/knowledge/ask"),
  ).toHaveLength(1);
});

test("natural-language reminder draft requires confirmation before write", async ({
  page,
}) => {
  const state = await installApi(page);
  state.plans = [];
  const initialReminders = state.reminders.length;
  await page.goto("/agent#task-planner");
  await page
    .getByRole("textbox", { name: "提醒内容", exact: true })
    .fill("下周三跟进星河科技在线测评");
  await page.getByRole("button", { name: "生成提醒草稿", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "确认并创建提醒", exact: true }),
  ).toBeVisible();
  expect(state.reminders).toHaveLength(initialReminders);
  await page
    .getByRole("button", { name: "确认并创建提醒", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "打开提醒中心", exact: true }),
  ).toBeVisible();
  expect(state.reminders).toHaveLength(initialReminders + 1);
  expect(
    state.calls.find(
      (call) => call.path === "/agent/task-plans" && call.method === "POST",
    )?.body.idempotency_key,
  ).toBeTruthy();
});

test("timezone recalculation uses a confirmation dialog", async ({ page }) => {
  const state = await installApi(page);
  await page.goto("/reminders");
  await page.getByRole("button", { name: /账户时区：Asia\/Shanghai/ }).click();
  await page
    .getByRole("textbox", { name: "账户时区", exact: true })
    .fill("Asia/Tokyo");
  await page
    .getByRole("button", { name: "保存时区并重算", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "保存时区并重算未来提醒",
    exact: true,
  });
  await expect(dialog).toBeVisible();
  expect(
    state.calls.filter((call) => call.path === "/auth/me/timezone"),
  ).toHaveLength(0);
  await dialog.getByRole("button", { name: "确认重算", exact: true }).click();
  await expect.poll(() => state.user.timezone).toBe("Asia/Tokyo");
  expect(
    state.calls.find((call) => call.path === "/auth/me/timezone")?.body
      .recalculate_future,
  ).toBe(true);
});

test("Skill approval and execution remain separate and cancel is safe", async ({
  page,
}) => {
  const state = await installApi(page);
  await page.goto("/skills");
  await page.getByRole("button", { name: "核对后批准", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "确认执行本地保存", exact: true }),
  ).toBeVisible();
  expect(state.packs).toHaveLength(0);
  await page
    .getByRole("button", { name: "确认执行本地保存", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "确认执行本地保存",
    exact: true,
  });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  expect(state.packs).toHaveLength(0);
  await page
    .getByRole("button", { name: "确认执行本地保存", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认保存", exact: true })
    .click();
  await expect.poll(() => state.packs.length).toBe(1);
  await page.getByRole("tab", { name: "已保存材料", exact: true }).click();
  const materials = page.getByRole("tabpanel", {
    name: "已保存材料",
    exact: true,
  });
  await materials.getByRole("button", { name: /星河科技.*后端工程师/ }).click();
  await expect(
    materials.getByText("项目经验草稿", { exact: true }),
  ).toBeVisible();
  expect(
    state.calls.filter(
      (call) => call.path === "/skills/approvals/approval-1/execute",
    ),
  ).toHaveLength(1);
});

test("mail creation, approval and final confirmation never send prematurely", async ({
  page,
}) => {
  const state = await installApi(page);
  state.actions = [];
  await page.goto("/actions");
  await page
    .getByRole("textbox", { name: "收件人邮箱", exact: true })
    .fill("recruiter@example.com");
  await page
    .getByRole("textbox", { name: "邮件主题", exact: true })
    .fill("核对后的申请材料");
  await page
    .getByRole("textbox", { name: "邮件正文", exact: true })
    .fill("这是一份人工检查后的申请材料。");
  await page
    .getByRole("button", { name: "创建待审批邮件", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "核对后批准", exact: true }),
  ).toBeVisible();
  expect(state.actions[0].status).toBe("pending");
  await page.getByRole("button", { name: "核对后批准", exact: true }).click();
  await page
    .getByRole("button", { name: "最终确认并发送", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "最终确认并发送邮件",
    exact: true,
  });
  await expect(
    dialog.getByText("收件人：recruiter@example.com", { exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByText("这是一份人工检查后的申请材料。", { exact: true }),
  ).toBeVisible();
  expect(
    state.calls.filter(
      (call) =>
        call.path.endsWith("/execute") &&
        call.path.startsWith("/external-actions/"),
    ),
  ).toHaveLength(0);
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  expect(state.actions[0].status).toBe("approved");
  await page
    .getByRole("button", { name: "最终确认并发送", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "确认发送", exact: true })
    .click();
  await expect.poll(() => state.actions[0].status).toBe("executed");
  expect(
    state.calls.filter(
      (call) =>
        call.path.endsWith("/execute") &&
        call.path.startsWith("/external-actions/"),
    ),
  ).toHaveLength(1);
});

test("401 and server errors stay actionable instead of an endless skeleton", async ({
  page,
}) => {
  await installApi(page, { unauthorized: true });
  await page.goto("/jobs");
  await expect(
    page.getByRole("link", { name: "去登录", exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("status", { name: "正在加载", exact: true }),
  ).toHaveCount(0);
  await page.unroute("**/api/v1/**");
  await installApi(page, {
    failures: { "/jobs": { status: 500, detail: "Test database unavailable" } },
  });
  await page.reload();
  await expect(
    page.getByRole("alert").filter({ hasText: "HTTP 500" }).first(),
  ).toBeVisible();
});

test("404 source evidence, empty collections and unknown route render safely", async ({
  page,
}) => {
  await installApi(page, {
    failures: {
      [`/agent/jobs/${JOB_ID}/evidence`]: {
        status: 404,
        detail: "岗位来源不存在",
      },
    },
  });
  await page.goto("/jobs");
  await page.getByRole("button", { name: "抽取依据", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "岗位来源不存在" }),
  ).toBeVisible();
  await page.unroute("**/api/v1/**");
  await installApi(page, { empty: true });
  await page.reload();
  await expect(page.getByText("还没有保存岗位", { exact: true })).toBeVisible();
  await page.goto("/missing-product-route");
  await expect(
    page.getByRole("heading", { name: "404", exact: true }),
  ).toBeVisible();
});

test("tablet and wide desktop retain a bounded workspace", async ({
  page,
}, testInfo) => {
  await installApi(page);
  for (const width of [768, 1920]) {
    await page.setViewportSize({ width, height: 1080 });
    await page.goto("/agent");
    await settle(page);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width + 1);
    await page.screenshot({
      path: testInfo.outputPath(`agent-${width}.png`),
      fullPage: true,
      animations: "disabled",
    });
  }
});

test("initial API failures stay retryable without false empty or SMTP states", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const state = await installApi(page);
  const cases = [
    {
      path: "/actions",
      prefixes: ["/api/v1/external-actions"],
      absent: ["SMTP 未配置", "目前没有外部动作记录"],
      recovered: "撰写邮件",
    },
    {
      path: "/skills",
      prefixes: ["/api/v1/skills"],
      absent: [
        "尚无 Skill 运行记录",
        "还没有已保存的申请准备包",
        "还没有审计记录",
      ],
      recovered: "配置任务",
    },
    {
      path: "/reminders",
      prefixes: ["/api/v1/reminders"],
      absent: ["还没有提醒", "还没有站内通知"],
      recovered: "完成在线测评",
    },
    {
      path: "/jobs",
      prefixes: ["/api/v1/jobs"],
      absent: ["还没有保存岗位", "没有符合条件的岗位"],
      recovered: "后端工程师",
    },
    {
      path: "/companies",
      prefixes: ["/api/v1/companies"],
      absent: ["还没有公司档案"],
      recovered: "星河科技",
    },
  ];
  for (const scenario of cases) {
    const matcher = (url: URL) =>
      scenario.prefixes.some(
        (prefix) =>
          url.pathname === prefix || url.pathname.startsWith(`${prefix}/`),
      );
    const failure = async (route: Route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Temporary test outage" }),
      });
    await page.route(matcher, failure);
    await page.goto(scenario.path);
    await expect(
      page.getByRole("alert").filter({ hasText: "HTTP 503" }).first(),
    ).toBeVisible();
    const retry = page.getByRole("button", { name: "重新载入", exact: true });
    await expect(retry).toBeVisible();
    for (const emptyText of scenario.absent)
      await expect(page.getByText(emptyText, { exact: true })).toHaveCount(0);
    await page.unroute(matcher, failure);
    await retry.click();
    await expect(
      page.getByText(scenario.recovered, { exact: true }).first(),
    ).toBeVisible();
    await expect(retry).toHaveCount(0);
  }
  expect(state.unhandled).toEqual([]);
});
