"use client";

import { createContext, useContext, type ReactNode } from "react";

const AdminEnvironmentContext = createContext({ allowDemoReset: false });

export function AdminEnvironmentProvider({
  allowDemoReset,
  children,
}: {
  allowDemoReset: boolean;
  children: ReactNode;
}) {
  return (
    <AdminEnvironmentContext.Provider value={{ allowDemoReset }}>
      {children}
    </AdminEnvironmentContext.Provider>
  );
}

export function useAdminEnvironment() {
  return useContext(AdminEnvironmentContext);
}
