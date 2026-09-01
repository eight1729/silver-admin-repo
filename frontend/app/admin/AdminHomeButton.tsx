"use client";

export const ADMIN_HOME_EVENT = "demo-admin:show-jobs";

export function AdminHomeButton() {
  return <button className="admin-home-link" type="button" onClick={() => window.dispatchEvent(new Event(ADMIN_HOME_EVENT))}>求人一覧へ戻る</button>;
}
