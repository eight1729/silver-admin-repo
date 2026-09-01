"use client";

import { useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import type { AdminLineSendMode } from "../lib/admin-api";
import { DEFAULT_CENTER_DISPLAY_NAME } from "./notification-templates";

const navigationItems = [
  { label: "ダッシュボード", icon: "⌂", href: "/admin/dashboard" },
  { label: "求人一覧", icon: "▤", href: "/admin/jobs" },
  { label: "通知作成", icon: "✉", href: "/admin" },
  { label: "送信履歴", icon: "↻", href: "/admin/history" },
  { label: "レポート", icon: "▥", href: "/admin/reports" },
  { label: "設定", icon: "⚙", href: "/admin/settings" },
] as const;

function modePresentation(mode: AdminLineSendMode | null) {
  if (mode?.mode !== "staging_live") return { label: "Fake", detail: "実LINE送信は行いません", tone: "fake" };
  if (mode.ready) return { label: "実LINE送信可能", detail: "検証者1名に限定", tone: "ready" };
  return { label: "実LINE送信ブロック中", detail: "送信設定を確認してください", tone: "blocked" };
}

export function AdminShell({ mode, children }: { mode: AdminLineSendMode | null; children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();
  const presentation = modePresentation(mode);
  return <div className="admin-workspace">
    <header className="admin-app-header">
      <div className="admin-app-title">
        <button className="admin-menu-toggle" type="button" aria-label={menuOpen ? "メニューを閉じる" : "メニューを開く"} aria-expanded={menuOpen} aria-controls="admin-sidebar-navigation" onClick={() => setMenuOpen((current) => !current)}><span aria-hidden="true">☰</span></button>
        <div><h1>スタッフ管理画面</h1><p>求人通知・マッチング管理</p></div>
      </div>
      <div className="admin-header-context" aria-label="現在の利用状況">
        <div className={`admin-mode admin-mode--${presentation.tone}`} role="status"><span className="admin-mode-mark" aria-hidden="true" /><span><strong>{presentation.label}</strong><small>{presentation.detail}</small></span></div>
        <div className="admin-safe-context"><span><small>操作担当</small><strong>準本番スタッフ</strong></span><span><small>所属</small><strong>{DEFAULT_CENTER_DISPLAY_NAME}</strong></span></div>
      </div>
    </header>
    <div className="admin-app-body">
      <aside className={`admin-sidebar${menuOpen ? " is-open" : ""}`} id="admin-sidebar-navigation">
        <nav aria-label="スタッフ管理メニュー"><ul>{navigationItems.map((item) => { const current = pathname === item.href; return <li key={item.label}><a className={`admin-nav-item${current ? " is-current" : ""}`} href={item.href} aria-current={current ? "page" : undefined} onClick={() => setMenuOpen(false)}><span className="admin-nav-icon" aria-hidden="true">{item.icon}</span><span>{item.label}</span></a></li>; })}</ul></nav>
      </aside>
      {menuOpen && <button className="admin-sidebar-backdrop" type="button" aria-label="メニューを閉じる" onClick={() => setMenuOpen(false)} />}
      <div className="admin-content">{children}</div>
    </div>
  </div>;
}
