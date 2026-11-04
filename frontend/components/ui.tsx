"use client";

import Link from "next/link";
import { useEffect, type ReactNode } from "react";
import {
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Group,
  Paper,
  Skeleton,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle, IconCheck, IconInbox } from "@tabler/icons-react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <Group justify="space-between" align="flex-start" mb="xl" gap="md">
      <Box miw={0}>
        <Title order={1} fz={{ base: 25, sm: 29 }} lh={1.25}>
          {title}
        </Title>
        {description && (
          <Text c="dimmed" size="sm" mt={8} maw={760}>
            {description}
          </Text>
        )}
      </Box>
      {actions && (
        <Group gap="xs" wrap="wrap">
          {actions}
        </Group>
      )}
    </Group>
  );
}
export function Feedback({
  error,
  notice,
  requiresLogin,
}: {
  error?: string;
  notice?: string;
  requiresLogin?: boolean;
}) {
  useEffect(() => {
    if (notice)
      notifications.show({
        message: notice,
        color: "teal",
        icon: <IconCheck size={17} />,
        autoClose: 4500,
      });
  }, [notice]);
  return (
    <Stack gap="sm" mb={error || notice || requiresLogin ? "md" : 0}>
      {error && (
        <Alert color="red" icon={<IconAlertCircle size={18} />} role="alert">
          {requiresLogin ? "登录后即可继续使用你的求职工作区。" : error}
        </Alert>
      )}
      {requiresLogin && (
        <Button component={Link} href="/login" variant="light" w="fit-content">
          去登录
        </Button>
      )}
      {notice && (
        <Alert color="teal" icon={<IconCheck size={18} />} role="status">
          {notice}
        </Alert>
      )}
    </Stack>
  );
}
export function LoadingState() {
  return (
    <Stack role="status" aria-label="正在加载" gap="md">
      <Skeleton h={24} w="35%" />
      <Skeleton h={90} />
      <Skeleton h={140} />
      <Skeleton h={90} />
    </Stack>
  );
}
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <Box p="xl" ta="center">
      <Stack align="center" gap="sm">
        <ThemeIcon variant="light" color="gray" size={46} radius="xl">
          <IconInbox size={23} />
        </ThemeIcon>
        <Text fw={600}>{title}</Text>
        {description && (
          <Text size="sm" c="dimmed" maw={460}>
            {description}
          </Text>
        )}
        {action}
      </Stack>
    </Box>
  );
}
const labels: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  cancelling: "取消中",
  succeeded: "已完成",
  confirmed: "已确认",
  failed: "失败",
  cancelled: "已取消",
  awaiting_confirmation: "待确认",
  needs_clarification: "待补充",
  scheduled: "已安排",
  paused: "已暂停",
  notified: "已通知",
  completed: "已完成",
  pending: "待审批",
  approved: "已批准",
  rejected: "已拒绝",
  executed: "已执行",
  executing: "执行中",
  outcome_unknown: "待核对",
  expired: "已过期",
  invalidated: "已失效",
};
export function StatusBadge({
  status,
  label,
}: {
  status: string;
  label?: string;
}) {
  const color = ["failed", "rejected", "invalidated"].includes(status)
    ? "red"
    : [
          "running",
          "queued",
          "cancelling",
          "pending",
          "awaiting_confirmation",
          "needs_clarification",
          "outcome_unknown",
          "executing",
        ].includes(status)
      ? "orange"
      : [
            "succeeded",
            "confirmed",
            "completed",
            "approved",
            "executed",
            "scheduled",
          ].includes(status)
        ? "teal"
        : "gray";
  return <Badge color={color}>{label ?? labels[status] ?? status}</Badge>;
}
export function Brand({
  href = "/dashboard",
  compact = false,
}: {
  href?: string;
  compact?: boolean;
}) {
  return (
    <Anchor
      component={Link}
      href={href}
      underline="never"
      c="var(--mantine-color-text)"
      aria-label="OfferPilot 工作台"
    >
      <Group gap={10} wrap="nowrap">
        <ThemeIcon size={34} radius="md" color="teal" fw={750} fz={20}>
          O
        </ThemeIcon>
        {!compact && (
          <Text
            component="span"
            fw={750}
            fz={18}
            style={{ letterSpacing: "-0.5px" }}
          >
            OfferPilot
          </Text>
        )}
      </Group>
    </Anchor>
  );
}
