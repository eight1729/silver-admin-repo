"use client";
import { useCallback, useEffect, useRef, useState } from "react";

// Each request owns its entry; an older completion cannot clear a newer request.
export function useLoadingTasks() {
  const pending = useRef(new Map<symbol, string>());
  const mounted = useRef(true);
  const [status, setStatus] = useState<string | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; pending.current.clear(); };
  }, []);
  const track = useCallback(async <T,>(label: string, action: () => Promise<T>): Promise<T> => {
    const key = Symbol();
    pending.current.set(key, label);
    if (mounted.current) setStatus(label);
    try { return await action(); }
    finally {
      pending.current.delete(key);
      if (mounted.current) setStatus([...pending.current.values()].at(-1) ?? null);
    }
  }, []);
  return { status, track };
}
