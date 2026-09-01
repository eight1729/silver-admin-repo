"use client";

import { useState } from "react";

import { color, radius, shadow, space } from "../design/tokens";

type CardProps = {
  children: React.ReactNode;
  onClick?: () => void;
  interactive?: boolean;
  style?: React.CSSProperties;
};

export function Card({ children, onClick, interactive, style }: CardProps) {
  const [hovered, setHovered] = useState(false);

  const baseStyle: React.CSSProperties = {
    background: color.surface,
    border: `1px solid ${hovered && interactive ? color.text : color.border}`,
    borderRadius: radius.lg,
    padding: space.lg,
    cursor: interactive ? "pointer" : undefined,
    boxShadow: hovered && interactive ? shadow.md : undefined,
    transform: hovered && interactive ? "translateY(-1px)" : undefined,
    transition: "box-shadow .15s, border-color .15s, transform .15s",
  };

  return (
    <div
      style={{ ...baseStyle, ...style }}
      onClick={onClick}
      onMouseEnter={() => interactive && setHovered(true)}
      onMouseLeave={() => interactive && setHovered(false)}
    >
      {children}
    </div>
  );
}
