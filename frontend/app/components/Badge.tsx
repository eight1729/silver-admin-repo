"use client";

import { color, font, radius, space } from "../design/tokens";

type BadgeProps = {
  children: React.ReactNode;
};

export function Badge({ children }: BadgeProps) {
  return (
    <span
      style={{
        display: "inline-block",
        background: color.surfaceMuted,
        color: color.text,
        borderRadius: radius.sm,
        padding: `${space.xs} ${space.sm}`,
        fontSize: font.size.xs,
        fontWeight: font.weight.semibold,
        whiteSpace: "nowrap",
        lineHeight: 1.6,
      }}
    >
      {children}
    </span>
  );
}
