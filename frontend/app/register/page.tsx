import Link from "next/link";
import { AuthForm } from "@/app/auth-form";

export default function RegisterPage() {
  return (
    <main className="auth-shell">
      <Link className="brand" href="/">
        <span className="brand-mark">O</span> OfferPilot
      </Link>
      <section className="auth-card">
        <p className="eyebrow">开始使用</p>
        <h1>创建求职工作区</h1>
        <p className="auth-intro">先建立账户，接下来逐步完善你的求职档案。</p>
        <AuthForm mode="register" />
      </section>
      <p className="auth-footnote">你可以随时管理或删除自己的数据。</p>
    </main>
  );
}
