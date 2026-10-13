"use client";

export const ADMIN_HOME_EVENT = "demo-admin:show-jobs";
export const ADMIN_NEW_EVENT = "demo-admin:new-notification";

export function AdminHomeButton() {
  return <button className="admin-button secondary" type="button" onClick={() => window.dispatchEvent(new Event(ADMIN_HOME_EVENT))}>求人一覧へ戻る</button>;
}
