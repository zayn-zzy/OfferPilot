"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";
import { apiRequest } from "@/lib/api";

type AuthMode = "login" | "register";

export function AuthForm({ mode }: { mode: AuthMode }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await apiRequest(`/api/v1/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      window.location.assign("/dashboard");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "请求失败，请稍后重试。");
      setBusy(false);
    }
  }

  const isRegister = mode === "register";

  return (
    <form className="auth-form" onSubmit={handleSubmit}>
      <label htmlFor="email">邮箱</label>
      <input
        autoComplete="email"
        id="email"
        name="email"
        onChange={(event) => setEmail(event.target.value)}
        placeholder="name@example.com"
        required
        type="email"
        value={email}
      />
      <label htmlFor="password">密码</label>
      <input
        autoComplete={isRegister ? "new-password" : "current-password"}
        id="password"
        minLength={isRegister ? 10 : 1}
        name="password"
        onChange={(event) => setPassword(event.target.value)}
        placeholder={isRegister ? "至少 10 个字符" : "输入你的密码"}
        required
        type="password"
        value={password}
      />
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="button button-primary form-submit" disabled={busy} type="submit">
        {busy ? "处理中…" : isRegister ? "创建账户" : "登录"}
      </button>
      <p className="auth-switch">
        {isRegister ? "已经有账户？" : "还没有账户？"}{" "}
        <Link href={isRegister ? "/login" : "/register"}>
          {isRegister ? "去登录" : "创建账户"}
        </Link>
      </p>
    </form>
  );
}
