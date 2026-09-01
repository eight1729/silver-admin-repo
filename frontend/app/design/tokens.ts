export const color = {
  bg: "#FFFFFF",
  surface: "#FFFFFF",
  surfaceMuted: "#F4F4F5",
  border: "#E4E4E7",
  text: "#111111",
  textMuted: "#71717A",
  accent: "#111111",
  onAccent: "#FFFFFF",
  disabledBg: "#D4D4D8",
  disabledText: "#FFFFFF",
  overlay: "rgba(0, 0, 0, 0.5)",
} as const;

export const space = {
  xs: "0.25rem",
  sm: "0.5rem",
  md: "0.75rem",
  lg: "1rem",
  xl: "1.5rem",
  xxl: "2rem",
} as const;

export const radius = { sm: "6px", md: "8px", lg: "12px", pill: "999px" } as const;

export const font = {
  family:
    "-apple-system, BlinkMacSystemFont, 'Hiragino Kaku Gothic ProN', 'Yu Gothic', Meiryo, sans-serif",
  size: {
    xs: "0.75rem",
    sm: "0.85rem",
    base: "0.95rem",
    md: "1.05rem",
    lg: "1.2rem",
    xl: "1.35rem",
  },
  weight: { regular: 400, medium: 500, semibold: 600, bold: 700 },
  lineHeight: { tight: 1.4, normal: 1.6, relaxed: 1.8 },
} as const;

export const shadow = {
  sm: "0 1px 2px rgba(0,0,0,0.06)",
  md: "0 6px 20px rgba(0,0,0,0.08)",
  sheet: "0 -4px 24px rgba(0,0,0,0.16)",
} as const;

export const layout = { maxWidth: "520px", formMaxWidth: "420px" } as const;
