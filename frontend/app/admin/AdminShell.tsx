"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import type { AdminLineSendMode } from "../lib/admin-api";
import { DEFAULT_CENTER_DISPLAY_NAME } from "./notification-templates";
import { modePresentation } from "./send-capability";
import { AdminHeaderActions } from "./AdminHeaderActions";
import { AdminHomeButton, ADMIN_NEW_EVENT } from "./AdminHomeButton";
import { attachSidebarFocus } from "./sidebar-focus";

const navigationItems = [
  { label: "ダッシュボード", icon: "⌂", href: "/admin/dashboard" },
  { label: "求人一覧", icon: "▤", href: "/admin/jobs" },
  { label: "通知作成", icon: "✉", href: "/admin" },
  { label: "送信履歴", icon: "↻", href: "/admin/history" },
  { label: "レポート", icon: "▥", href: "/admin/reports" },
  { label: "設定", icon: "⚙", href: "/admin/settings" },
] as const;

export function AdminShell({ mode, children }: { mode: AdminLineSendMode | null; children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  useEffect(() => {
    if (menuOpen && sidebar.current && menuTrigger.current) {
      return attachSidebarFocus(sidebar.current, menuTrigger.current, () => setMenuOpen(false));
    }
  }, [menuOpen]);
  const pathname = usePathname();
  const presentation = modePresentation(mode);
  return <div className="admin-workspace">
    <header className="admin-app-header">
      <div className="admin-app-title">
        <button ref={menuTrigger} className="admin-menu-toggle" type="button" aria-label={menuOpen ? "メニューを閉じる" : "メニューを開く"} aria-expanded={menuOpen} aria-controls="admin-sidebar-navigation" onClick={() => setMenuOpen((current) => !current)}><span aria-hidden="true">☰</span></button>
        <div><h1>スタッフ管理画面</h1><p>求人通知・マッチング管理</p></div>
      </div>
      <div className="admin-header-context" aria-label="現在の利用状況">
        <div className={`admin-mode admin-mode--${presentation.tone}`} role="status"><span className="admin-mode-mark" aria-hidden="true" /><span><strong>{presentation.label}</strong><small>{presentation.detail}</small></span></div>
        <div className="admin-safe-context"><span><small>操作担当</small><strong>準本番スタッフ</strong></span><span><small>所属</small><strong>{DEFAULT_CENTER_DISPLAY_NAME}</strong></span></div>
      </div>
      <div className="admin-header-actions">
        {pathname === "/admin" && <AdminHomeButton />}
        <AdminHeaderActions />
      </div>
    </header>
    <div className="admin-app-body">
      <aside ref={sidebar} hidden={!menuOpen} className={`admin-sidebar${menuOpen ? " is-open" : ""}`} id="admin-sidebar-navigation" role="dialog" aria-modal={menuOpen ? true : undefined} aria-label="スタッフ管理メニュー" tabIndex={-1}>
        <button type="button" className="admin-sidebar-close" onClick={() => setMenuOpen(false)}>メニューを閉じる</button>
        <nav aria-label="スタッフ管理メニュー"><ul>{navigationItems.map((item) => { const current = pathname === item.href; return <li key={item.label}><a className={`admin-nav-item${current ? " is-current" : ""}`} href={item.href} aria-current={current ? "page" : undefined} onClick={(event) => {
          setMenuOpen(false);
          if (item.href === "/admin" && pathname === "/admin" && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
            if (!window.dispatchEvent(new Event(ADMIN_NEW_EVENT, { cancelable: true }))) event.preventDefault();
          }
        }}><span className="admin-nav-icon" aria-hidden="true">{item.icon}</span><span>{item.label}</span></a></li>; })}</ul></nav>
      </aside>
      {menuOpen && <button className="admin-sidebar-backdrop" type="button" tabIndex={-1} aria-label="メニューを閉じる" onClick={() => setMenuOpen(false)} />}
      <div className="admin-content">{children}</div>
    </div>
  </div>;
}
