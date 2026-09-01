"use client";

import { useEffect, useId, useRef } from "react";

import { color, font, shadow, space } from "../design/tokens";

type ModalProps = {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
};

export function Modal({ title, onClose, children, footer }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusableSelector = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
    const focusables = () => Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? []);
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Tab") {
        const items = focusables();
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";
    const initial = dialogRef.current?.querySelector<HTMLElement>("[data-modal-initial-focus]") ?? focusables()[0];
    initial?.focus();
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
      previouslyFocused?.focus();
    };
  }, [onClose]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: color.overlay,
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
    >
      <div
        ref={dialogRef}
        style={{
          background: color.surface,
          borderRadius: "20px 20px 0 0",
          width: "100%",
          maxWidth: "540px",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          position: "relative",
          boxShadow: shadow.sheet,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          aria-label="詳細を閉じる"
          style={{
            position: "absolute",
            top: space.lg,
            right: space.lg,
            background: color.surfaceMuted,
            color: color.text,
            border: "none",
            borderRadius: "50%",
            width: "2.4rem",
            height: "2.4rem",
            fontSize: font.size.base,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: font.weight.bold,
            flexShrink: 0,
            zIndex: 1,
          }}
        >
          ✕
        </button>

        <div
          style={{
            overflowY: "auto",
            padding: `${space.xl} ${space.lg} ${space.lg}`,
            flexGrow: 1,
          }}
        >
          <h2
            id={titleId}
            style={{
              fontSize: font.size.lg,
              fontWeight: font.weight.bold,
              color: color.text,
              margin: `0 2.8rem ${space.xl} 0`,
              lineHeight: font.lineHeight.tight,
            }}
          >
            {title}
          </h2>
          <div id={descriptionId}>{children}</div>
        </div>

        {footer && (
          <div
            style={{
              display: "flex",
              gap: space.md,
              padding: `${space.md} ${space.lg} ${space.xl}`,
              flexShrink: 0,
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
