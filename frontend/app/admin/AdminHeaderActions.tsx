"use client";

import { createContext, useContext, type ReactNode } from "react";

// AuthBoundary owns the action; the shell only chooses its visible placement.
export const AdminHeaderActionsContext = createContext<ReactNode>(null);

export function AdminHeaderActions() {
  return <>{useContext(AdminHeaderActionsContext)}</>;
}
