"use client";
import Link from "next/link";
import { type FormEvent, useState } from "react";
import {
  Alert,
  Anchor,
  Button,
  PasswordInput,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { IconAlertCircle, IconArrowRight } from "@tabler/icons-react";
import { apiRequest } from "@/lib/api";
export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isRegister = mode === "register";
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
      setError(
        cause instanceof Error ? cause.message : "请求失败，请稍后重试。",
      );
      setBusy(false);
    }
  }
  return (
    <form onSubmit={handleSubmit}>
      <Stack gap="md">
        <TextInput
          label="邮箱"
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="name@example.com"
          required
          value={email}
          onChange={(event) => setEmail(event.currentTarget.value)}
        />
        <PasswordInput
          label="密码"
          id="password"
          name="password"
          autoComplete={isRegister ? "new-password" : "current-password"}
          minLength={isRegister ? 10 : 1}
          placeholder={isRegister ? "至少 10 个字符" : "输入你的密码"}
          required
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          visibilityToggleButtonProps={{ "aria-label": "显示或隐藏密码" }}
        />
        {error && (
          <Alert color="red" icon={<IconAlertCircle size={17} />} role="alert">
            {error}
          </Alert>
        )}
        <Button
          type="submit"
          loading={busy}
          fullWidth
          rightSection={<IconArrowRight size={17} />}
        >
          {isRegister ? "创建账户" : "登录"}
        </Button>
        <Text size="sm" c="dimmed" ta="center">
          {isRegister ? "已经有账户？" : "还没有账户？"}{" "}
          <Anchor
            component={Link}
            href={isRegister ? "/login" : "/register"}
            size="sm"
          >
            {isRegister ? "去登录" : "创建账户"}
          </Anchor>
        </Text>
      </Stack>
    </form>
  );
}
