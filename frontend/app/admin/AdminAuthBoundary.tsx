"use client";

import { useEffect, useState, type ReactNode } from "react";
import { StaffLogin } from "./StaffLogin";
import { getStaffAuthState, logoutStaff, startStaffAuth, subscribeStaffAuth, type StaffAuthState } from "./staff-auth";

export function AdminAuthBoundary({ children, required = true }: { children: ReactNode; required?: boolean }) {
  const [state, setState] = useState<StaffAuthState | "loading">("loading");
  const [denied, setDenied] = useState<401 | 403 | null>(null);
  useEffect(() => {
    if (required) {
      const update = () => setState(getStaffAuthState());
      const unsubscribe = subscribeStaffAuth(update);
      startStaffAuth(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "");
      update();
      return unsubscribe;
    }
    const listener = (event: Event) => {
      const status = (event as CustomEvent<{ status?: number }>).detail?.status;
      if (status === 401 || status === 403) setDenied(status);
    };
    globalThis.addEventListener("admin-auth-failure", listener);
    return () => globalThis.removeEventListener("admin-auth-failure", listener);
  }, [required]);
  if (required) {
    if (state === "loading") return <p>認証状態を確認しています。</p>;
    if (state === "unauthenticated") return <StaffLogin />;
    const logout = <button type="button" onClick={() => { logoutStaff(); window.location.replace("/auth-required"); }}>ログアウト</button>;
    if (state === "forbidden") return <main><h1>管理画面を表示できません</h1><p>この画面を利用する権限がありません。</p>{logout}</main>;
    return <>{logout}{children}</>;
  }
  if (denied) {
    return <main><h1>管理画面を表示できません</h1><p>{denied === 401 ? "認証が必要です。" : "この画面を利用する権限がありません。"}</p></main>;
  }
  return children;
}
