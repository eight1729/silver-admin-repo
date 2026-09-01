"use client";

import { color, font, layout, space } from "../design/tokens";

type StatusScreenProps = {
  title?: string;
  subtitle?: string;
  tone?: "default" | "error";
  children?: React.ReactNode;
};

export function StatusScreen({ title, subtitle, tone = "default", children }: StatusScreenProps) {
  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: color.bg,
        padding: `${space.xxl} ${space.lg}`,
        boxSizing: "border-box",
      }}
    >
      <div style={{ width: "100%", maxWidth: layout.formMaxWidth }}>
        {title && (
          <p
            style={{
              fontSize: font.size.md,
              fontWeight: font.weight.bold,
              color: color.text,
              textAlign: "center",
              margin: `0 0 ${tone === "error" ? space.lg : space.xs}`,
            }}
          >
            {title}
          </p>
        )}
        {subtitle && (
          <p
            style={{
              fontSize: font.size.sm,
              color: color.textMuted,
              textAlign: "center",
              lineHeight: font.lineHeight.normal,
              margin: `0 0 ${space.xl}`,
            }}
          >
            {subtitle}
          </p>
        )}
        {children && <div style={{ textAlign: "left" }}>{children}</div>}
      </div>
    </main>
  );
}
