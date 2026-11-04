"use client";
import { ActionIcon, Box, Menu, useMantineColorScheme } from "@mantine/core";
import {
  IconCheck,
  IconDeviceDesktop,
  IconMoon,
  IconSun,
} from "@tabler/icons-react";
export function ThemeSwitcher() {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon
          aria-label="切换主题"
          variant="subtle"
          color="gray"
          size="lg"
        >
          <Box darkHidden>
            <IconSun size={20} />
          </Box>
          <Box lightHidden>
            <IconMoon size={20} />
          </Box>
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>外观主题</Menu.Label>
        {(
          [
            { value: "light", label: "浅色", icon: IconSun },
            { value: "dark", label: "深色", icon: IconMoon },
            { value: "auto", label: "跟随系统", icon: IconDeviceDesktop },
          ] as const
        ).map((item) => (
          <Menu.Item
            key={item.value}
            leftSection={<item.icon size={16} />}
            rightSection={
              colorScheme === item.value ? <IconCheck size={15} /> : null
            }
            onClick={() => setColorScheme(item.value)}
          >
            {item.label}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
