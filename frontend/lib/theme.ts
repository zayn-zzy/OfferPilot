import { createTheme, type CSSVariablesResolver } from "@mantine/core";
import classes from "@/components/controls.module.css";

export const themeVariables: CSSVariablesResolver = () => ({
  variables: {},
  light: {
    "--mantine-color-dimmed": "var(--app-muted-light)",
    "--mantine-color-placeholder": "var(--app-muted-light)",
    "--mantine-color-disabled-color": "var(--app-muted-light)",
    "--mantine-color-yellow-light-color": "var(--app-warning-ink-light)",
    "--mantine-color-orange-light-color": "var(--app-warning-ink-light)",
    "--mantine-color-red-light-color": "var(--app-danger-ink-light)",
    "--mantine-color-blue-light-color": "var(--app-info-ink-light)",
  },
  dark: {
    "--mantine-color-dimmed": "var(--app-muted-dark)",
    "--mantine-color-placeholder": "var(--app-muted-dark)",
    "--mantine-color-disabled-color": "var(--app-muted-dark)",
    "--mantine-color-yellow-light-color": "var(--app-warning-ink-dark)",
    "--mantine-color-orange-light-color": "var(--app-warning-ink-dark)",
    "--mantine-color-red-light-color": "var(--app-danger-ink-dark)",
    "--mantine-color-blue-light-color": "var(--app-info-ink-dark)",
  },
});

export const theme = createTheme({
  autoContrast: true,
  primaryColor: "teal",
  primaryShade: { light: 7, dark: 7 },
  fontFamily: '"DM Sans", "Noto Sans SC", system-ui, sans-serif',
  headings: {
    fontFamily: '"DM Sans", "Noto Sans SC", system-ui, sans-serif',
    fontWeight: "650",
  },
  defaultRadius: "md",
  colors: {
    teal: [
      "#eaf8f4",
      "#cff0e6",
      "#9de0ce",
      "#67cdb4",
      "#3dbb9e",
      "#21a98b",
      "#168f76",
      "#137761",
      "#12624f",
      "#104f41",
    ],
    dark: [
      "#d9dfe3",
      "#aeb8c0",
      "#87939e",
      "#59646e",
      "#3a434c",
      "#2a323a",
      "#222a31",
      "#1b2229",
      "#151b21",
      "#10161b",
    ],
  },
  spacing: {
    xs: "0.5rem",
    sm: "0.75rem",
    md: "1rem",
    lg: "1.5rem",
    xl: "2rem",
  },
  radius: {
    xs: "0.25rem",
    sm: "0.375rem",
    md: "0.5rem",
    lg: "0.75rem",
    xl: "1rem",
  },
  components: {
    Input: { classNames: { input: classes.input } },
    Button: { defaultProps: { size: "sm", fw: 600 } },
    Paper: { defaultProps: { radius: "lg" } },
    Card: { defaultProps: { radius: "lg", padding: "lg", withBorder: true } },
    Modal: {
      defaultProps: {
        centered: true,
        overlayProps: { backgroundOpacity: 0.3, blur: 2 },
      },
    },
    Drawer: {
      defaultProps: { overlayProps: { backgroundOpacity: 0.3, blur: 2 } },
    },
    Tooltip: { defaultProps: { withArrow: true, openDelay: 250 } },
    TextInput: { defaultProps: { size: "sm" } },
    Select: { defaultProps: { size: "sm" } },
    Textarea: { defaultProps: { size: "sm" } },
    Badge: { defaultProps: { variant: "light", radius: "sm", tt: "none" } },
  },
});
