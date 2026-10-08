"use client";

import "./staff-login.css";

import { useEffect, useRef, useState } from "react";
import { renderStaffSignIn, startStaffAuth } from "./staff-auth";

export function StaffLogin() {
  const button = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID?.trim() ?? "";
  useEffect(() => {
    startStaffAuth(clientId);
    if (!clientId || !button.current) return;
    let active = true;
    renderStaffSignIn(button.current, (accepted) => {
      if (!active) return;
      if (accepted) window.location.replace("/");
      else setFailed(true);
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [clientId]);
  return <main className="admin-login"><section className="admin-login-card" aria-labelledby="admin-login-title">
    <h1 id="admin-login-title">管理画面</h1>
    <p>登録済みスタッフのGoogleアカウントでログインしてください。</p>
    {!clientId ? <p role="alert">ログイン設定が未完了のため利用できません。</p> : <div className="admin-login-button" ref={button} />}
    {failed && <p role="alert">ログインできませんでした。ページを再読み込みしてお試しください。</p>}
  </section></main>;
}
