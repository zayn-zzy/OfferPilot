"use client";

import "dayjs/locale/zh-cn";
import { MantineProvider } from "@mantine/core";
import { DatesProvider } from "@mantine/dates";
import { ModalsProvider } from "@mantine/modals";
import { Notifications } from "@mantine/notifications";
import { theme, themeVariables } from "@/lib/theme";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <MantineProvider
      theme={theme}
      cssVariablesResolver={themeVariables}
      defaultColorScheme="auto"
    >
      <DatesProvider settings={{ locale: "zh-cn", firstDayOfWeek: 1 }}>
        <ModalsProvider labels={{ confirm: "确认", cancel: "取消" }}>
          <Notifications position="bottom-right" limit={3} />
          {children}
        </ModalsProvider>
      </DatesProvider>
    </MantineProvider>
  );
}
