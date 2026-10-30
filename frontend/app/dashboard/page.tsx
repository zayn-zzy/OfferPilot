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
          <button className="text-button" onClick={logout} type="button">退出登录</button>
        </div>
      </header>
      <section className="dashboard-welcome">
        <p className="eyebrow">求职工作台</p>
        <h1>{user ? `你好，${user.email}` : error ? requiresLogin ? "请重新登录" : "暂时无法载入工作区" : "正在载入你的工作区…"}</h1>
        <p>{error || "账户已经准备好。下一步将逐步加入个人档案、岗位管理和投递看板。"}</p>
      </section>
      <section className="setup-panel">
        <div className="setup-icon">01</div>
        <div>
          <h2>账户与基础服务已就绪</h2>
          <p>当前阶段完成账户与全栈服务骨架。后续模块会在此基础上增加个人档案和岗位管理。</p>
        </div>
        <span className="status-pill">基础模块</span>
      </section>
    </main>
  );
}
