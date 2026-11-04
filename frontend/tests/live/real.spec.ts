import { randomUUID } from "node:crypto";
import { expect, test, type Page, type Response } from "@playwright/test";
import type { JobPosting } from "../../lib/api";

type Resume = {
  id: string;
  confirmed_at: string | null;
  extracted_text: string;
};

function mutation(page: Page, method: string, path: string) {
  return page.waitForResponse((response: Response) => {
    const url = new URL(response.url());
    return (
      url.pathname === `/api/v1${path}` &&
      response.request().method() === method
    );
  });
}

async function newJobForm(page: Page) {
  await page.getByRole("button", { name: "添加岗位", exact: true }).click();
  await page.getByRole("menuitem", { name: "新增岗位", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "新增岗位", exact: true });
  await expect(drawer).toBeVisible();
  return drawer.getByRole("form", { name: "新增岗位", exact: true });
}

test("real Next.js proxy persists account, profile, confirmed resume and merged job", async ({
  page,
}, testInfo) => {
  const runId = randomUUID();
  const email = `mantine-live-${runId}@example.com`;
  const password = `OfferPilot-live-${randomUUID()}`;
  const company = `真实浏览器回归公司${runId.slice(0, 8)}`;
  const initialTitle = "全栈开发实习生";
  const updatedTitle = "全栈开发工程师";
  const sourceUrl = `https://example.com/offerpilot-live/${runId}`;
  const resumeText =
    "张同学\n2027 年软件工程本科毕业。\n校园交易平台项目：使用 Python、SQL 和 React 实现商品管理、搜索及用户登录，负责接口设计与前端集成。";
  const pageErrors: string[] = [];
  const browserApiRequests: { origin: string; path: string }[] = [];
  let registered = false;
  let savedJob: JobPosting;
  let applicationId: string | undefined;
  let historyCount = 0;

  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/"))
      browserApiRequests.push({ origin: url.origin, path: url.pathname });
  });

  try {
    await test.step("register through the page, sign out and sign in again", async () => {
      await page.goto("/register");
      await page.getByRole("textbox", { name: /^邮箱/ }).fill(email);
      await page.locator('input[name="password"]').fill(password);
      const registeredResponse = mutation(page, "POST", "/auth/register");
      await page.getByRole("button", { name: "创建账户", exact: true }).click();
      const response = await registeredResponse;
      registered = response.ok();
      expect(response.status()).toBe(201);
      await expect(page).toHaveURL(/\/dashboard$/);
      const current = await page.request.get("/api/v1/auth/me");
      expect(current.status()).toBe(200);
      expect((await current.json()).email).toBe(email);

      await page.getByRole("button", { name: "账户菜单", exact: true }).click();
      const loggedOutResponse = mutation(page, "POST", "/auth/logout");
      await page
        .getByRole("menuitem", { name: "退出登录", exact: true })
        .click();
      expect((await loggedOutResponse).status()).toBe(204);
      await expect(page).toHaveURL(/\/login$/);
      expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);

      await page.getByRole("textbox", { name: /^邮箱/ }).fill(email);
      await page.locator('input[name="password"]').fill(password);
      const loggedInResponse = mutation(page, "POST", "/auth/login");
      await page.getByRole("button", { name: "登录", exact: true }).click();
      expect((await loggedInResponse).status()).toBe(200);
      await expect(page).toHaveURL(/\/dashboard$/);
    });

    await test.step("save real candidate profile values and preserve them after reload", async () => {
      await page.goto("/profile");
      await page
        .getByRole("textbox", { name: "专业", exact: true })
        .fill("软件工程");
      await page
        .getByRole("textbox", { name: "学历", exact: true })
        .fill("本科");
      const graduation = page
        .getByRole("textbox", { name: "毕业年份", exact: true })
        .or(page.getByRole("spinbutton", { name: "毕业年份", exact: true }));
      await graduation.fill("2027");
      const city = page.getByRole("textbox", { name: "目标城市", exact: true });
      await city.fill("上海");
      await city.press("Enter");
      const savedResponse = mutation(page, "PUT", "/profile");
      await page.getByRole("button", { name: "保存档案", exact: true }).click();
      expect((await savedResponse).status()).toBe(200);
      const stored = await page.request.get("/api/v1/profile");
      expect(stored.status()).toBe(200);
      expect(await stored.json()).toMatchObject({
        major: "软件工程",
        education: "本科",
        graduation_year: 2027,
        target_cities: ["上海"],
      });
      await page.reload();
      await expect(
        page.getByRole("textbox", { name: "专业", exact: true }),
      ).toHaveValue("软件工程");
    });

    await test.step("paste a resume, review its persisted text and explicitly confirm it", async () => {
      await page.getByRole("tab", { name: /简历版本/ }).click();
      await page
        .getByRole("textbox", { name: "也可以直接粘贴简历文本", exact: true })
        .fill(resumeText);
      const createdResponse = mutation(page, "POST", "/resumes/text");
      await page
        .getByRole("button", { name: "保存为新版本", exact: true })
        .click();
      const response = await createdResponse;
      expect(response.status()).toBe(201);
      const created = (await response.json()) as Resume;
      expect(created.confirmed_at).toBeNull();
      const preview = page.getByRole("dialog", {
        name: "简历解析预览",
        exact: true,
      });
      await expect(preview).toBeVisible();
      await expect(preview.locator("pre")).toHaveText(resumeText);
      const before = await page.request.get(`/api/v1/resumes/${created.id}`);
      expect(before.status()).toBe(200);
      expect((await before.json()).confirmed_at).toBeNull();
      const confirmedResponse = mutation(
        page,
        "POST",
        `/resumes/${created.id}/confirm`,
      );
      await preview
        .getByRole("button", { name: "确认这份简历", exact: true })
        .click();
      expect((await confirmedResponse).status()).toBe(200);
      await expect(
        preview.getByText("已由你确认，可用于后续匹配。", { exact: true }),
      ).toBeVisible();
      const after = await page.request.get(`/api/v1/resumes/${created.id}`);
      const confirmed = (await after.json()) as Resume;
      expect(confirmed.confirmed_at).not.toBeNull();
      expect(confirmed.extracted_text).toBe(resumeText);
      await preview
        .getByRole("button", { name: "关闭预览", exact: true })
        .click();
      await expect(preview).toHaveCount(0);
    });

    await test.step("manually save a job, edit in its card and verify reload persistence", async () => {
      await page.goto("/jobs");
      const form = await newJobForm(page);
      await form
        .getByRole("textbox", { name: "公司名称", exact: true })
        .fill(company);
      await form
        .getByRole("textbox", { name: "职位名称", exact: true })
        .fill(initialTitle);
      await form
        .getByRole("textbox", { name: "岗位来源", exact: true })
        .fill(sourceUrl);
      const createdResponse = mutation(page, "POST", "/jobs");
      await form.getByRole("button", { name: "保存岗位", exact: true }).click();
      const response = await createdResponse;
      expect(response.status()).toBe(201);
      savedJob = (await response.json()) as JobPosting;
      const card = page.getByRole("article", {
        name: `${company} ${initialTitle}`,
        exact: true,
      });
      await expect(card).toBeVisible();
      await expect(card).toBeInViewport();
      await expect(page.locator(".job-card").first()).toHaveAttribute(
        "id",
        `job-${savedJob.id}`,
      );
      await card.getByRole("button", { name: "编辑", exact: true }).click();
      const editor = card.getByRole("form", { name: "编辑岗位", exact: true });
      await expect(editor).toBeVisible();
      await editor
        .getByRole("textbox", { name: "职位名称", exact: true })
        .fill(updatedTitle);
      const updatedResponse = mutation(page, "PUT", `/jobs/${savedJob.id}`);
      await editor
        .getByRole("button", { name: "保存修改", exact: true })
        .click();
      expect((await updatedResponse).status()).toBe(200);
      await expect(
        page.getByRole("article", {
          name: `${company} ${updatedTitle}`,
          exact: true,
        }),
      ).toBeVisible();
      const stored = await page.request.get(`/api/v1/jobs/${savedJob.id}`);
      expect(stored.status()).toBe(200);
      expect(await stored.json()).toMatchObject({
        id: savedJob.id,
        title: updatedTitle,
        source_url: sourceUrl,
      });
      await page.reload();
      await expect(
        page.getByRole("article", {
          name: `${company} ${updatedTitle}`,
          exact: true,
        }),
      ).toBeVisible();

      // Setup an application through the same Next.js proxy to prove that merging
      // keeps its identity and history while the actual merge remains a UI action.
      const applicationResponse = await page.request.put(
        `/api/v1/jobs/${savedJob.id}/application`,
        { data: { status: "applied", notes: "合并后应保留的投递备注" } },
      );
      expect(applicationResponse.status()).toBe(200);
      applicationId = ((await applicationResponse.json()) as JobPosting)
        .application?.id;
      expect(applicationId).toBeTruthy();
      const history = await page.request.get(
        `/api/v1/jobs/${savedJob.id}/application/history`,
      );
      expect(history.status()).toBe(200);
      historyCount = (await history.json()).length;
      expect(historyCount).toBeGreaterThan(0);
    });

    await test.step("resolve a duplicate source with UI merge and keep the application", async () => {
      const form = await newJobForm(page);
      await form
        .getByRole("textbox", { name: "公司名称", exact: true })
        .fill(company);
      await form
        .getByRole("textbox", { name: "职位名称", exact: true })
        .fill("新输入标题不能覆盖原有标题");
      await form
        .getByRole("textbox", { name: "工作城市", exact: true })
        .fill("上海");
      await form
        .getByRole("textbox", { name: "岗位来源", exact: true })
        .fill(sourceUrl);
      const conflictResponse = mutation(page, "POST", "/jobs");
      await form.getByRole("button", { name: "保存岗位", exact: true }).click();
      expect((await conflictResponse).status()).toBe(409);
      await expect(
        form.getByText("发现已有岗位", { exact: true }),
      ).toBeVisible();
      const mergedResponse = mutation(
        page,
        "POST",
        `/jobs/${savedJob.id}/merge`,
      );
      await form
        .getByRole("button", { name: "合并到这个岗位", exact: true })
        .click();
      expect((await mergedResponse).status()).toBe(200);
      await expect(page.getByRole("dialog")).toHaveCount(0);
      await expect(
        page.getByRole("article", {
          name: `${company} ${updatedTitle}`,
          exact: true,
        }),
      ).toBeInViewport();
      const stored = await page.request.get(`/api/v1/jobs/${savedJob.id}`);
      expect(stored.status()).toBe(200);
      expect(await stored.json()).toMatchObject({
        id: savedJob.id,
        title: updatedTitle,
        city: "上海",
        application: {
          id: applicationId,
          status: "applied",
          notes: "合并后应保留的投递备注",
        },
      });
      const list = await page.request.get("/api/v1/jobs");
      expect(
        (await list.json()).filter(
          (job: JobPosting) => job.source_url === sourceUrl,
        ),
      ).toHaveLength(1);
      const history = await page.request.get(
        `/api/v1/jobs/${savedJob.id}/application/history`,
      );
      expect((await history.json()).length).toBe(historyCount);
      await page.reload();
      await expect(
        page.getByRole("article", {
          name: `${company} ${updatedTitle}`,
          exact: true,
        }),
      ).toBeVisible();
      await page.screenshot({
        path: testInfo.outputPath("real-jobs-after-merge.png"),
        fullPage: true,
        animations: "disabled",
      });
    });

    expect(pageErrors).toEqual([]);
    const origin = new URL(page.url()).origin;
    expect(browserApiRequests.length).toBeGreaterThan(0);
    expect(
      browserApiRequests.every((request) => request.origin === origin),
    ).toBe(true);
    expect(
      browserApiRequests.filter((request) =>
        /\/(research|knowledge\/(ask|reindex)|agent\/job-extractions|external-actions)(\/|$)/.test(
          request.path,
        ),
      ),
    ).toEqual([]);
  } finally {
    if (registered) {
      // Re-authenticate even if the test failed during the logout/login step.
      // All cleanup still passes through the real Next.js /api proxy.
      const login = await page.request.post("/api/v1/auth/login", {
        data: { email, password },
      });
      expect(
        login.status(),
        "temporary live account must be available for cleanup",
      ).toBe(200);
      const deletion = await page.request.delete("/api/v1/account/me", {
        data: { current_password: password, confirmation_email: email },
      });
      expect(
        deletion.status(),
        "temporary live account and its owned data must be removed",
      ).toBe(204);
      expect((await page.request.get("/api/v1/auth/me")).status()).toBe(401);
    }
  }
});
