"use client";

import { useState } from "react";

import { color, font, radius, space } from "../design/tokens";

type FieldProps = {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  autoFocus?: boolean;
  inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"];
};

export function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  required,
  autoFocus,
  inputMode,
}: FieldProps) {
  const [focused, setFocused] = useState(false);

  return (
    <div>
      <label
        htmlFor={id}
        style={{
          display: "block",
          fontSize: font.size.base,
          color: color.text,
          marginBottom: space.xs,
        }}
      >
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        autoFocus={autoFocus}
        inputMode={inputMode}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          width: "100%",
          boxSizing: "border-box",
          padding: `${space.md} ${space.md}`,
          fontSize: font.size.base,
          border: `1px solid ${focused ? color.text : color.border}`,
          borderRadius: radius.md,
          color: color.text,
          background: color.surface,
          outline: "none",
        }}
      />
    </div>
  );
}
