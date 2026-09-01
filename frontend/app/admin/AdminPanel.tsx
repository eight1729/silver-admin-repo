import type { ReactNode } from "react";

export function AdminPanel({ number, title, description, badge, status, actions, children }: { number: number; title: string; description?: string; badge?: string; status?: string; actions?: ReactNode; children: ReactNode }) {
  const headingId = `admin-panel-${number}-title`;
  return <section className={`admin-panel admin-panel--${number}`} aria-labelledby={headingId}>
    <header className="admin-panel-header"><div className="admin-panel-title-row"><span className="admin-panel-number" aria-hidden="true">{number}</span><div><div className="admin-panel-heading-line"><h2 id={headingId}>{title}</h2>{badge && <span className="admin-panel-count">{badge}</span>}</div>{description && <p>{description}</p>}</div></div>{(status || actions) && <div className="admin-panel-tools">{status && <span className="admin-panel-status">{status}</span>}{actions}</div>}</header>
    <div className="admin-panel-body">{children}</div>
  </section>;
}
