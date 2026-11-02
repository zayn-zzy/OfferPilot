"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, apiRequest, type User } from "@/lib/api";

export default function DashboardPage() {
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);

  useEffect(() => {
    apiRequest<User>("/api/v1/auth/me")
      .then(setUser)
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : "无法载入工作区。");
        setRequiresLogin(cause instanceof ApiError && cause.status === 401);
      });
  }, []);

  async function logout() {
    await apiRequest("/api/v1/auth/logout", { method: "POST" });
    window.location.assign("/login");
  }

  return (
    <main className="dashboard-shell">
      <header className="dashboard-topbar">
        <Link className="brand" href="/">
          <span className="brand-mark">O</span> OfferPilot
        </Link>
        <div className="dashboard-actions">
          <Link className="text-link" href="/profile">个人档案</Link>
          <Link className="text-link" href="/knowledge">资料问答</Link>
          <Link className="text-link" href="/skills">Agent Skills</Link>
          <Link className="text-link" href="/jobs">岗位管理</Link>
          <Link className="text-link" href="/reminders">提醒中心</Link>
          <button className="text-button" onClick={logout} type="button">退出登录</button>
        </div>
      </header>
      <section className="dashboard-welcome">
        <p className="eyebrow">求职工作台</p>
        <h1>{user ? `你好，${user.email}` : error ? requiresLogin ? "请重新登录" : "暂时无法载入工作区" : "正在载入你的工作区…"}</h1>
        <p>{error || "管理个人档案、查询简历笔记并记录岗位进度。"}</p>
      </section>
      <section className="setup-panel">
        <div className="setup-icon">01</div>
        <div>
          <h2>求职资料与岗位管理已就绪</h2>
          <p>你的个人资料、简历版本、岗位来源和投递阶段会按账户隔离保存。</p>
        </div>
        <Link className="button button-primary" href="/jobs">管理岗位</Link>
      </section>
    </main>
  );
}
