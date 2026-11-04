import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";

const root = path.resolve(".hallmark");
const routes = [
  "home",
  "login",
  "register",
  "dashboard",
  "jobs",
  "profile",
  "knowledge",
  "companies",
  "reminders",
  "agent",
  "skills",
  "actions",
  "settings",
];
const labels = [
  "首页",
  "登录",
  "注册",
  "求职总览",
  "岗位管理",
  "个人档案",
  "资料问答",
  "公司档案",
  "提醒中心",
  "Agent 工作区",
  "求职 Skills",
  "外部动作",
  "设置",
];
const walk = (directory) =>
  existsSync(directory)
    ? readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
        entry.isDirectory()
          ? walk(path.join(directory, entry.name))
          : [path.join(directory, entry.name)],
      )
    : [];
const captures = walk(path.resolve("test-results/artifacts"));
mkdirSync(path.join(root, "states"), { recursive: true });
const sections = routes.map((route, index) => {
  for (const phase of ["before", "after"]) {
    if (!existsSync(path.join(root, phase, `${route}-1440.png`)))
      throw new Error(
        `Missing ${phase}/${route}-1440.png; run the capture tests first.`,
      );
  }
  const links = [];
  for (const [theme, viewport, label] of [
    ["light", "mobile", "手机浅色"],
    ["dark", "desktop", "桌面深色"],
    ["dark", "mobile", "手机深色"],
  ]) {
    const filename = `${route}-${theme}-${viewport}.png`;
    const source = captures.find((file) => path.basename(file) === filename);
    if (source) {
      copyFileSync(source, path.join(root, "states", filename));
      links.push(`<a href="states/${filename}">${label}</a>`);
    }
  }
  return `<section id="${route}"><h2>${labels[index]} <code>/${route === "home" ? "" : route}</code></h2><div class="links">${links.join(" ")}</div><div class="compare"><figure><figcaption>改版前</figcaption><img loading="lazy" src="before/${route}-1440.png" alt="${labels[index]}改版前"></figure><figure><figcaption>Mantine 改版后</figcaption><img loading="lazy" src="after/${route}-1440.png" alt="${labels[index]}改版后"></figure></div></section>`;
});
writeFileSync(
  path.join(root, "compare.html"),
  `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OfferPilot 前端改版对比</title><style>:root{--canvas:#f5f7f9;--ink:#18262e;--line:#cbd5df;--accent:#137761;--paper:#fff;--font:system-ui,sans-serif}*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--ink);font-family:var(--font)}main{max-width:1900px;margin:auto;padding:24px}h1{font-size:28px}nav,.links{display:flex;gap:16px;flex-wrap:wrap}a{color:var(--accent)}section{margin:48px 0}h2 code{font-size:14px}.compare{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}figure{margin:0;background:var(--paper);border:1px solid var(--line);border-radius:8px;overflow:clip}figcaption{padding:14px;font-weight:600;border-bottom:1px solid var(--line)}img{width:100%;height:auto;display:block}.links{margin-bottom:16px}@media(max-width:800px){.compare{grid-template-columns:minmax(0,1fr)}}</style><main><h1>OfferPilot 全站界面对比</h1><p>13 个路由使用同一批受控演示资料，桌面截图均为 1440 × 1000 视口完整页面。演示资料不来自真实账户。手机及深色截图可通过各页面链接查看。</p><nav>${routes.map((route, index) => `<a href="#${route}">${labels[index]}</a>`).join("")}</nav>${sections.join("")}</main></html>`,
);
console.log("UI comparison written to .hallmark/compare.html");
