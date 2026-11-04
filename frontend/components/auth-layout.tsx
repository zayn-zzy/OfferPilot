"use client";

import {
  Box,
  Container,
  Group,
  Paper,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import {
  IconBriefcase2,
  IconCalendarEvent,
  IconShieldCheck,
} from "@tabler/icons-react";
import { AuthForm } from "@/app/auth-form";
import { Brand } from "./ui";
import { ThemeSwitcher } from "./theme-switcher";
import classes from "./public.module.css";

export function AuthLayout({ mode }: { mode: "login" | "register" }) {
  return (
    <main className={classes.auth}>
      <Container size={1160}>
        <Group justify="space-between" py="lg">
          <Brand href="/" />
          <ThemeSwitcher />
        </Group>
        <div className={classes.authGrid}>
          <Box visibleFrom="md" pr="xl">
            <Text size="sm" fw={600} c="teal" mb="md">
              让求职准备更有条理
            </Text>
            <Title order={2} fz={42} lh={1.2}>
              把精力留给
              <br />
              真正重要的机会。
            </Title>
            <Text c="dimmed" mt="lg" maw={390} lh={1.8}>
              岗位信息、申请进展和准备材料，集中在一个属于你的工作区。
            </Text>
            <Stack gap="xl" mt={42}>
              {[
                {
                  icon: IconBriefcase2,
                  title: "岗位与进展",
                  text: "保存来源，维护投递阶段和下一步。",
                },
                {
                  icon: IconCalendarEvent,
                  title: "安排与提醒",
                  text: "确认日期与时区，及时跟进重要任务。",
                },
                {
                  icon: IconShieldCheck,
                  title: "由你确认",
                  text: "Agent 整理草稿，重要操作经过你的检查。",
                },
              ].map((item) => (
                <Group key={item.title} align="flex-start" wrap="nowrap">
                  <ThemeIcon variant="light" size={40}>
                    <item.icon size={22} />
                  </ThemeIcon>
                  <Box>
                    <Text fw={600} size="sm">
                      {item.title}
                    </Text>
                    <Text c="dimmed" size="sm" mt={4}>
                      {item.text}
                    </Text>
                  </Box>
                </Group>
              ))}
            </Stack>
          </Box>
          <Paper p={{ base: "lg", sm: 36 }} withBorder shadow="sm">
            <Title order={1} size="h2">
              {mode === "login" ? "欢迎回到 OfferPilot" : "创建你的求职工作区"}
            </Title>
            <Text c="dimmed" size="sm" mt="xs" mb="xl">
              {mode === "login"
                ? "登录后继续你的求职计划。"
                : "建立账户后，即可整理岗位、简历和提醒。"}
            </Text>
            <AuthForm mode={mode} />
            <Text size="xs" c="dimmed" mt="xl" ta="center">
              {mode === "login"
                ? "你的求职资料仅供当前账户使用。"
                : "你可以随时导出或删除自己的数据。"}
            </Text>
          </Paper>
        </div>
      </Container>
    </main>
  );
}
