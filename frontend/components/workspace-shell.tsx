"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ActionIcon,
  Anchor,
  AppShell,
  Avatar,
  Breadcrumbs,
  Burger,
  Button,
  Divider,
  Drawer,
  Group,
  Indicator,
  Kbd,
  Menu,
  NavLink,
  Popover,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { useDisclosure, useLocalStorage } from "@mantine/hooks";
import { Spotlight, spotlight } from "@mantine/spotlight";
import {
  IconBell,
  IconBriefcase2,
  IconBuilding,
  IconCalendarEvent,
  IconCheck,
  IconChevronRight,
  IconFileCv,
  IconHome,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
  IconLogout,
  IconMail,
  IconNotebook,
  IconRobot,
  IconSearch,
  IconSettings,
  IconSparkles,
} from "@tabler/icons-react";
import { apiRequest, type User, type ReminderCenter } from "@/lib/api";
import { Brand, Feedback } from "./ui";
import { ThemeSwitcher } from "./theme-switcher";
import classes from "./workspace-shell.module.css";

const groups = [
  {
    label: "工作台",
    items: [
      { href: "/dashboard", label: "求职总览", icon: IconHome },
      { href: "/agent", label: "Agent 工作区", icon: IconRobot },
    ],
  },
  {
    label: "岗位与招聘",
    items: [
      { href: "/jobs", label: "岗位管理", icon: IconBriefcase2 },
      { href: "/companies", label: "公司档案", icon: IconBuilding },
      { href: "/reminders", label: "提醒中心", icon: IconCalendarEvent },
    ],
  },
  {
    label: "资料与准备",
    items: [
      { href: "/profile", label: "个人档案", icon: IconFileCv },
      { href: "/knowledge", label: "资料问答", icon: IconNotebook },
      { href: "/skills", label: "求职 Skills", icon: IconSparkles },
    ],
  },
  {
    label: "集成与账户",
    items: [
      { href: "/actions", label: "外部动作", icon: IconMail },
      { href: "/settings", label: "设置", icon: IconSettings },
    ],
  },
];

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useLocalStorage({
    key: "offerpilot-sidebar-collapsed",
    defaultValue: false,
  });
  const [mobileOpened, mobile] = useDisclosure(false);
  const [user, setUser] = useState<User | null>(null);
  const [center, setCenter] = useState<ReminderCenter | null>(null);
  const [shellError, setShellError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  const current = groups
    .flatMap((group) => group.items)
    .find((item) => pathname === item.href);

  useEffect(() => {
    let active = true;
    mobile.close();
    apiRequest<User>("/api/v1/auth/me")
      .then((value) => {
        if (active) setUser(value);
      })
      .catch(() => {
        if (active) {
          setUser(null);
          setCenter(null);
        }
      });
    return () => {
      active = false;
    };
  }, [pathname]);

  useEffect(() => {
    if (!user) return;
    let active = true;
    const refresh = () =>
      void apiRequest<ReminderCenter>("/api/v1/reminders")
        .then((value) => {
          if (active) setCenter(value);
        })
        .catch(() => {});
    refresh();
    const timer = window.setInterval(refresh, 60000);
    window.addEventListener("focus", refresh);
    window.addEventListener("offerpilot:notifications-changed", refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("offerpilot:notifications-changed", refresh);
    };
  }, [user?.id, pathname]);

  async function logout() {
    setLoggingOut(true);
    try {
      await apiRequest("/api/v1/auth/logout", { method: "POST" });
      window.location.assign("/login");
    } catch (cause) {
      setShellError(
        cause instanceof Error ? cause.message : "退出失败，请重试。",
      );
      setLoggingOut(false);
    }
  }
  async function markRead(id: string) {
    try {
      await apiRequest(`/api/v1/notifications/${id}/read`, { method: "POST" });
      setCenter((previous) =>
        previous
          ? {
              ...previous,
              unread_count: Math.max(
                0,
                previous.unread_count -
                  (previous.notifications.find((item) => item.id === id)
                    ?.read_at
                    ? 0
                    : 1),
              ),
              notifications: previous.notifications.map((item) =>
                item.id === id
                  ? { ...item, read_at: new Date().toISOString() }
                  : item,
              ),
            }
          : previous,
      );
      window.dispatchEvent(new Event("offerpilot:notifications-changed"));
    } catch (cause) {
      setShellError(cause instanceof Error ? cause.message : "无法更新通知。");
    }
  }
  function navigation(compact = false) {
    return (
      <nav
        aria-label={compact ? "折叠主导航" : "主导航"}
        className={classes.navigation}
      >
        {groups.map((group) => (
          <div key={group.label}>
            {!compact && (
              <Text className={classes.groupLabel}>{group.label}</Text>
            )}
            {group.items.map((item) => {
              const link = (
                <NavLink
                  className={classes.navLink}
                  component={Link}
                  href={item.href}
                  key={item.href}
                  active={pathname === item.href}
                  aria-current={pathname === item.href ? "page" : undefined}
                  aria-label={item.label}
                  label={compact ? undefined : item.label}
                  leftSection={<item.icon size={19} stroke={1.7} />}
                  onClick={mobile.close}
                  styles={
                    compact
                      ? {
                          root: { justifyContent: "center", paddingInline: 12 },
                          section: { marginInlineEnd: 0 },
                        }
                      : undefined
                  }
                />
              );
              return compact ? (
                <Tooltip label={item.label} position="right" key={item.href}>
                  {link}
                </Tooltip>
              ) : (
                link
              );
            })}
          </div>
        ))}
      </nav>
    );
  }
  return (
    <>
      <AppShell
        layout="alt"
        header={{ height: 64 }}
        navbar={{
          width: collapsed ? 76 : 248,
          breakpoint: "md",
          collapsed: { mobile: true },
        }}
        transitionDuration={0}
        padding={0}
      >
      <AppShell.Navbar className={classes.navbar} visibleFrom="md">
          <div className={classes.brand}>
            <Brand compact={collapsed} />
          </div>
          <AppShell.Section grow component={ScrollArea}>
            {navigation(collapsed)}
          </AppShell.Section>
          <AppShell.Section className={classes.footer}>
            <Tooltip
              label={collapsed ? "展开侧栏" : "折叠侧栏"}
              position="right"
            >
              <Button
                variant="subtle"
                color="gray"
                fullWidth
                onClick={() => setCollapsed((value) => !value)}
                aria-label={collapsed ? "展开侧栏" : "折叠侧栏"}
                leftSection={
                  collapsed ? (
                    <IconLayoutSidebarLeftExpand size={19} />
                  ) : (
                    <IconLayoutSidebarLeftCollapse size={19} />
                  )
                }
              >
                {!collapsed && "折叠侧栏"}
              </Button>
            </Tooltip>
          </AppShell.Section>
        </AppShell.Navbar>
        <AppShell.Header className={classes.header}>
          <div className={classes.headerInner}>
            <Group gap="sm" wrap="nowrap" miw={0}>
              <Burger
                opened={mobileOpened}
                onClick={mobile.toggle}
                hiddenFrom="md"
                aria-label="打开导航菜单"
                size="sm"
              />
              <Breadcrumbs separator={<IconChevronRight size={13} />}>
                <Anchor
                  component={Link}
                  href="/dashboard"
                  size="sm"
                  c="dimmed"
                  visibleFrom="sm"
                >
                  工作空间
                </Anchor>
                <Text size="sm" fw={600} lineClamp={1}>
                  {current?.label ?? "工作台"}
                </Text>
              </Breadcrumbs>
            </Group>
            <Group gap={6} wrap="nowrap">
              <Button
                className={classes.jump}
                variant="default"
                size="compact-sm"
                onClick={spotlight.open}
                leftSection={<IconSearch size={16} />}
                rightSection={
                <Kbd visibleFrom="sm" size="xs" fz={12}>
                    ⌘ K
                  </Kbd>
                }
                aria-label="快速跳转"
              >
                <Text size="xs" visibleFrom="sm">
                  快速跳转
                </Text>
              </Button>
              <ThemeSwitcher />
              <Popover width={340} position="bottom-end" shadow="md" withArrow>
                <Popover.Target>
                  <Indicator
                    disabled={!center?.unread_count}
                    label={center?.unread_count}
                    size={16}
                    offset={4}
                  >
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      size="lg"
                      aria-label="通知"
                    >
                      <IconBell size={20} />
                    </ActionIcon>
                  </Indicator>
                </Popover.Target>
                <Popover.Dropdown maw="calc(100% - 24px)">
                  <Group justify="space-between">
                    <Text fw={600} size="sm">
                      站内通知
                    </Text>
                    <Anchor component={Link} href="/reminders" size="xs">
                      查看全部
                    </Anchor>
                  </Group>
                  <ScrollArea.Autosize mah={330} mt="xs">
                    {center?.notifications.length ? (
                      center.notifications.slice(0, 5).map((notification) => (
                        <div
                          className={classes.notification}
                          key={notification.id}
                        >
                          <Group
                            justify="space-between"
                            wrap="nowrap"
                            align="flex-start"
                          >
                            <Stack gap={4}>
                              <Text
                                size="sm"
                                fw={notification.read_at ? 400 : 600}
                              >
                                {notification.title}
                              </Text>
                              <Text size="xs" c="dimmed" lineClamp={2}>
                                {notification.body}
                              </Text>
                            </Stack>
                            {!notification.read_at && (
                              <ActionIcon
                                variant="light"
                                aria-label={`标记已读：${notification.title}`}
                                onClick={() => void markRead(notification.id)}
                              >
                                <IconCheck size={16} />
                              </ActionIcon>
                            )}
                          </Group>
                        </div>
                      ))
                    ) : (
                      <Text size="sm" c="dimmed" py="lg">
                        {user ? "暂无站内通知。" : "登录后查看你的通知。"}
                      </Text>
                    )}
                  </ScrollArea.Autosize>
                </Popover.Dropdown>
              </Popover>
              <Divider orientation="vertical" mx={4} visibleFrom="sm" />
              <Menu position="bottom-end" width={230}>
                <Menu.Target>
                  <ActionIcon
                    size="lg"
                    variant="transparent"
                    aria-label="账户菜单"
                  >
                    <Avatar color="teal" size={32} radius="xl">
                      {user?.email.charAt(0).toUpperCase() ?? "O"}
                    </Avatar>
                  </ActionIcon>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Label style={{ overflowWrap: "anywhere" }}>
                    {user?.email ?? "尚未登录"}
                  </Menu.Label>
                  {user && (
                    <Text size="xs" c="dimmed" px="sm" pb="xs">
                      {user.timezone}
                    </Text>
                  )}
                  <Menu.Item
                    component={Link}
                    href="/profile"
                    leftSection={<IconFileCv size={17} />}
                  >
                    个人档案
                  </Menu.Item>
                  <Menu.Item
                    component={Link}
                    href="/settings"
                    leftSection={<IconSettings size={17} />}
                  >
                    账户设置
                  </Menu.Item>
                  <Menu.Divider />
                  {user ? (
                    <Menu.Item
                      color="red"
                      leftSection={<IconLogout size={17} />}
                      disabled={loggingOut}
                      onClick={() => void logout()}
                    >
                      {loggingOut ? "正在退出…" : "退出登录"}
                    </Menu.Item>
                  ) : (
                    <Menu.Item component={Link} href="/login">
                      去登录
                    </Menu.Item>
                  )}
                </Menu.Dropdown>
              </Menu>
            </Group>
          </div>
        </AppShell.Header>
        <AppShell.Main>
          <div className={classes.content}>
            <Feedback error={shellError} />
            {children}
          </div>
        </AppShell.Main>
      </AppShell>
      <Drawer
        opened={mobileOpened}
        onClose={mobile.close}
        title={<Brand />}
        size={280}
        hiddenFrom="md"
      >
        {navigation()}
      </Drawer>
      <Spotlight
        actions={groups.flatMap((group) =>
          group.items.map((item) => ({
            id: item.href,
            label: item.label,
            description: group.label,
            onClick: () => router.push(item.href),
            leftSection: <item.icon size={21} />,
          })),
        )}
        nothingFound="没有匹配的页面"
        highlightQuery
        searchProps={{
          leftSection: <IconSearch size={20} />,
          placeholder: "跳转到岗位、资料或 Agent 工作区…",
        }}
        shortcut={["mod + K"]}
      />
    </>
  );
}
