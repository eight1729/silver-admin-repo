"use client";

import { color, font, radius, space } from "../design/tokens";

type ButtonProps = {
  children: React.ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: "primary" | "secondary";
  fullWidth?: boolean;
  disabled?: boolean;
};

export function Button({
  children,
  onClick,
  type = "button",
  variant = "primary",
  fullWidth,
  disabled,
}: ButtonProps) {
  const base: React.CSSProperties = {
    padding: `${space.md} ${space.lg}`,
    borderRadius: radius.md,
    fontSize: font.size.md,
    fontWeight: font.weight.semibold,
    width: fullWidth ? "100%" : undefined,
    cursor: disabled ? "not-allowed" : "pointer",
  };

  const variantStyle: React.CSSProperties = disabled
    ? variant === "primary"
      ? { background: color.disabledBg, color: color.disabledText, border: "none" }
      : { background: color.surface, color: color.textMuted, border: `1px solid ${color.border}` }
    : variant === "primary"
      ? { background: color.accent, color: color.onAccent, border: "none" }
      : { background: color.surface, color: color.text, border: `1px solid ${color.border}` };

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{ ...base, ...variantStyle }}
    >
      {children}
    </button>
  );
}
