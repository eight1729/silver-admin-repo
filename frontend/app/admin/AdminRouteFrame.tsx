"use client";

import { useEffect, useState, type ReactNode } from "react";
import { adminApi, type AdminLineSendMode } from "../lib/admin-api";
import { AdminShell } from "./AdminShell";

export function AdminRouteFrame({ title, description, children }: { title: string; description: string; children: ReactNode | ((mode: AdminLineSendMode | null) => ReactNode) }) {
  const [mode, setMode] = useState<AdminLineSendMode | null>(null);
  const [modeUnavailable, setModeUnavailable] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void adminApi.lineSendMode(controller.signal).then(setMode).catch((error) => {
      if (!(error instanceof DOMException && error.name === "AbortError")) setModeUnavailable(true);
    });
    return () => controller.abort();
  }, []);
  return <AdminShell mode={mode}><main className="admin-main admin-route-page"><header className="admin-route-heading"><h2>{title}</h2><p>{description}</p></header>{modeUnavailable && <div className="admin-info" role="status">現在の送信モードを取得できませんでした。</div>}{typeof children === "function" ? children(mode) : children}</main></AdminShell>;
}
