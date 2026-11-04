"use client";

import Link from "next/link";
import {
  Anchor,
  Badge,
  Box,
  Button,
  Container,
  Group,
  Image,
  SimpleGrid,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import {
  IconArrowRight,
  IconBriefcase2,
  IconCalendarEvent,
  IconFileDescription,
} from "@tabler/icons-react";
import { Brand } from "@/components/ui";
import { ThemeSwitcher } from "@/components/theme-switcher";
import classes from "@/components/public.module.css";

export default function HomePage() {
  return (
    <main>
      <Container size={1160}>
        <Group justify="space-between" py="lg">
          <Brand href="/" />
          <Group gap="sm">
            <ThemeSwitcher />
            <Button
              component={Link}
              href="/login"
              variant="subtle"
              color="gray"
            >
              登录
            </Button>
            <Button component={Link} href="/register">
              创建账户
            </Button>
          </Group>
        </Group>
        <section className={classes.hero}>
          <Badge variant="light" mb="lg">
            求职流程工作台
          </Badge>
          <Title order={1} className={classes.heroTitle}>
            你的下一份机会，
            <br />
            从清晰的下一步开始。
          </Title>
          <Text
            c="dimmed"
            fz={{ base: "md", sm: "lg" }}
            lh={1.8}
            maw={620}
            mx="auto"
            mt="lg"
          >
            把岗位、申请进展和时间安排放在一起。让 Agent
            整理信息与准备草稿，重要决定由你确认。
          </Text>
          <Group justify="center" mt="xl">
            <Button
              component={Link}
              href="/register"
              size="md"
              rightSection={<IconArrowRight size={18} />}
            >
              创建求职工作区
            </Button>
            <Button component={Link} href="/login" variant="default" size="md">
              登录工作台
            </Button>
          </Group>
        </section>
        <section className={classes.preview} aria-label="工作台预览">
          <Group className={classes.previewHeading} justify="space-between">
            <Text fw={600} size="sm">
              OfferPilot 求职工作台
            </Text>
            <Badge color="gray">演示界面</Badge>
          </Group>
          <Image
            src="/product-preview.png"
            alt="OfferPilot 实际工作台界面的演示截图"
            width={1440}
            height={900}
            fit="contain"
          />
          <Text p="sm" size="xs" c="dimmed" ta="center">
            截图来自实际产品界面，使用演示资料，不代表你的账户数据。
          </Text>
        </section>
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xl">
          {[
            {
              icon: IconBriefcase2,
              title: "岗位有据可查",
              text: "导入招聘信息，核对原文引用，在同一张岗位卡片里维护申请进度。",
            },
            {
              icon: IconFileDescription,
              title: "准备更有方向",
              text: "从已确认简历和个人笔记检索证据，生成待检查的求职材料草稿。",
            },
            {
              icon: IconCalendarEvent,
              title: "跟进有条不紊",
              text: "记录日期与时区，把自然语言待办整理为经过你确认的提醒。",
            },
          ].map((feature) => (
            <Box className={classes.feature} key={feature.title}>
              <ThemeIcon variant="light" size={44} mb="md">
                <feature.icon size={24} />
              </ThemeIcon>
              <Title order={2} size="h4">
                {feature.title}
              </Title>
              <Text c="dimmed" size="sm" mt="sm" lh={1.8}>
                {feature.text}
              </Text>
            </Box>
          ))}
        </SimpleGrid>
        <Group className={classes.footer} justify="space-between">
          <Brand href="/" />
          <Text size="xs" c="dimmed">
            申请材料由你检查并提交。当前不自动投递或完成测评。
          </Text>
          <Anchor component={Link} href="/login" size="sm">
            进入工作台
          </Anchor>
        </Group>
      </Container>
    </main>
  );
}
