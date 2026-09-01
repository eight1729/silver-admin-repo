"use client";

import { useEffect, useState, type ReactNode } from "react";

export function AdminAuthBoundary({ children }: { children: ReactNode }) {
  const [denied, setDenied] = useState<401 | 403 | null>(null);
  useEffect(() => {
    const listener = (event: Event) => {
      const status = (event as CustomEvent<{ status?: number }>).detail?.status;
      if (status === 401 || status === 403) setDenied(status);
    };
    globalThis.addEventListener("admin-auth-failure", listener);
    return () => globalThis.removeEventListener("admin-auth-failure", listener);
  }, []);
  if (denied) {
    return <main><h1>管理画面を表示できません</h1><p>{denied === 401 ? "認証が必要です。" : "この画面を利用する権限がありません。"}</p></main>;
  }
  return children;
}
