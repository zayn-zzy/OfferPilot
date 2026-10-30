import Link from "next/link";
import { AuthForm } from "@/app/auth-form";

export default function LoginPage() {
  return (
    <main className="auth-shell">
      <Link className="brand" href="/">
        <span className="brand-mark">O</span> OfferPilot
      </Link>
      <section className="auth-card">
        <p className="eyebrow">欢迎回来</p>
        <h1>登录你的工作台</h1>
        <p className="auth-intro">继续整理岗位进度和求职计划。</p>
        <AuthForm mode="login" />
      </section>
      <p className="auth-footnote">你的账户信息由 OfferPilot 安全保管。</p>
    </main>
  );
}
