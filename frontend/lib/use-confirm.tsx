"use client";

import { useCallback, type ReactNode } from "react";
import { modals } from "@mantine/modals";
import { Text } from "@mantine/core";

type Confirmation = {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
};
export function useConfirm() {
  return useCallback(
    (options: Confirmation) =>
      new Promise<boolean>((resolve) => {
        modals.openConfirmModal({
          title: options.title,
          children:
            typeof options.message === "string" ? (
              <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                {options.message}
              </Text>
            ) : (
              options.message
            ),
          labels: { confirm: options.confirmLabel ?? "确认", cancel: "取消" },
          confirmProps: { color: options.danger ? "red" : "teal" },
          onConfirm: () => resolve(true),
          onCancel: () => resolve(false),
          onClose: () => resolve(false),
        });
      }),
    [],
  );
}
