"use client";

import { useEffect, useRef } from "react";
import "./loading-overlay.css";

export function LoadingOverlay({ active, status = "処理中…" }: { active: boolean; status?: string }) {
  const overlay = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!active) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    overlay.current?.focus();
    const keepFocus = (event: FocusEvent) => {
      if (!overlay.current?.contains(event.target as Node)) overlay.current?.focus();
    };
    const preventTab = (event: KeyboardEvent) => {
      if (event.key === "Tab") event.preventDefault();
    };
    document.addEventListener("focusin", keepFocus);
    document.addEventListener("keydown", preventTab, true);
    return () => {
      document.removeEventListener("focusin", keepFocus);
      document.removeEventListener("keydown", preventTab, true);
      if (previous?.isConnected) previous.focus();
    };
  }, [active]);
  if (!active) return null;
  return <div className="admin-loading-overlay" ref={overlay} tabIndex={-1}
    role="status" aria-live="polite" aria-busy="true" aria-label={status}>
    <div className="admin-loading-content">
      <span className="admin-loading-spinner" aria-hidden="true" />
      <span>{status}</span>
    </div>
  </div>;
}
