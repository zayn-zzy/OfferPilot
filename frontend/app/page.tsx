import Link from "next/link";

export default function HomePage() {
  return (
    <main className="landing-shell">
      <nav className="topbar">
        <Link className="brand" href="/">
          <span className="brand-mark">O</span> OfferPilot
        </Link>
        <Link className="text-link" href="/login">
          登录
        </Link>
      </nav>
      <section className="hero">
        <p className="eyebrow">你的求职流程工作台</p>
        <h1>把求职琐事<br />整理成清晰的下一步。</h1>
        <p className="hero-copy">
          集中管理岗位、申请进度和时间安排。让 Agent 帮你整理信息与准备草稿，重要决定由你确认。
        </p>
        <div className="hero-actions">
          <Link className="button button-primary" href="/register">
            创建账户
          </Link>
          <Link className="button button-secondary" href="/login">
            登录工作台
          </Link>
        </div>
        <div className="preview-card" aria-label="工作台预览">
          <div className="preview-header">
            <span>本周求职计划</span>
            <span className="preview-date">秋招 · 2026</span>
          </div>
          <div className="preview-stat-row">
            <div><strong>03</strong><span>待跟进</span></div>
            <div><strong>02</strong><span>即将截止</span></div>
            <div><strong>01</strong><span>面试安排</span></div>
          </div>
          <div className="preview-task">
            <span className="task-dot" />
            <div><strong>检查产品经理岗位要求</strong><small>今天 · 岗位研究</small></div>
            <span className="task-tag">待办</span>
          </div>
          <div className="preview-task">
            <span className="task-dot task-dot-muted" />
            <div><strong>更新某公司申请进度</strong><small>周五 · 申请跟进</small></div>
            <span className="task-tag task-tag-muted">计划中</span>
          </div>
        </div>
        <p className="trust-note">申请内容由你检查并提交 · 简历信息仅用于你的求职工作区</p>
      </section>
    </main>
  );
}
