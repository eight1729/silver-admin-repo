import { registerAdminAccessTokenProvider } from "../lib/admin-api";

export type StaffAuthState = "unauthenticated" | "authenticated" | "forbidden";
type GoogleIdentity = {
  initialize: (options: { client_id: string; callback: (response: { credential: string }) => void; ux_mode: "popup"; auto_select: false }) => void;
  renderButton: (element: HTMLElement, options: { type: "standard"; theme: "outline"; size: "large" }) => void;
  disableAutoSelect: () => void;
};
declare global {
  interface Window { google?: { accounts: { id: GoogleIdentity } } }
}

const STORAGE_KEY = "admin_staff_id_token";
let token: string | null = null;
let state: StaffAuthState = "unauthenticated";
let started = false;
let clientId = "";
let expiryTimer: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<() => void>();
let gisLoading: Promise<GoogleIdentity> | undefined;
let gisInitialized = false;
let credentialResult: ((accepted: boolean) => void) | undefined;

// Payload decoding is only a UI expiry check. Backend verifies every Bearer JWT.
function expiresAt(value: string): number {
  try {
    const parts = value.split(".");
    if (parts.length !== 3) return 0;
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const { exp } = JSON.parse(atob(payload.padEnd(Math.ceil(payload.length / 4) * 4, "=")));
    return typeof exp === "number" && Number.isFinite(exp) ? exp * 1000 : 0;
  } catch { return 0; }
}

function notify() { listeners.forEach((listener) => listener()); }
function routingHint(present: boolean) {
  // UX routing hint only; never an authentication or authorization credential.
  document.cookie = `admin_authenticated=${present ? "1" : ""}; Path=/; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}${present ? "" : "; Max-Age=0"}`;
}

export function clearStaffSession() {
  token = null;
  state = "unauthenticated";
  clearTimeout(expiryTimer);
  try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* Storage may be disabled. */ }
  routingHint(false);
  notify();
}

export function getStaffToken(): string | null {
  if (token && expiresAt(token) <= Date.now()) clearStaffSession();
  return token;
}

export function acceptStaffCredential(credential: string): boolean {
  if (!clientId || expiresAt(credential) <= Date.now()) {
    clearStaffSession();
    return false;
  }
  try { sessionStorage.setItem(STORAGE_KEY, credential); } catch {
    // Login navigation reloads the page: do not claim a restorable session exists.
    clearStaffSession();
    return false;
  }
  token = credential;
  state = "authenticated";
  routingHint(true);
  clearTimeout(expiryTimer);
  const checkExpiry = () => {
    if (getStaffToken()) expiryTimer = setTimeout(checkExpiry, Math.min(expiresAt(credential) - Date.now(), 2147483647));
  };
  checkExpiry();
  notify();
  return true;
}

export function startStaffAuth(googleClientId: string) {
  registerAdminAccessTokenProvider(getStaffToken);
  if (started) { getStaffToken(); return; }
  started = true;
  clientId = googleClientId.trim();
  window.addEventListener("admin-auth-failure", (event) => {
    const status = (event as CustomEvent<{ status: number }>).detail?.status;
    if (status === 401) clearStaffSession();
    if (status === 403) { state = "forbidden"; notify(); }
  });
  let saved: string | null = null;
  try { saved = sessionStorage.getItem(STORAGE_KEY); } catch { /* No persisted session. */ }
  if (!saved || !acceptStaffCredential(saved)) clearStaffSession();
}

export function getStaffAuthState() { return state; }
export function subscribeStaffAuth(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function logoutStaff() {
  clearStaffSession();
  window.google?.accounts.id.disableAutoSelect();
}

function loadGoogleIdentity(): Promise<GoogleIdentity> {
  if (window.google?.accounts.id) return Promise.resolve(window.google.accounts.id);
  if (!gisLoading) {
    gisLoading = new Promise<GoogleIdentity>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://accounts.google.com/gsi/client";
      script.async = true;
      script.onload = () => window.google?.accounts.id ? resolve(window.google.accounts.id) : reject(new Error("google_login_unavailable"));
      script.onerror = () => { script.remove(); reject(new Error("google_login_unavailable")); };
      document.head.appendChild(script);
    }).catch((error) => { gisLoading = undefined; throw error; });
  }
  return gisLoading;
}

export async function renderStaffSignIn(element: HTMLElement, onResult: (accepted: boolean) => void) {
  if (!clientId) throw new Error("google_client_id_missing");
  const identity = await loadGoogleIdentity();
  if (!element.isConnected) return;
  credentialResult = onResult;
  if (!gisInitialized) {
    identity.initialize({
      client_id: clientId,
      ux_mode: "popup",
      auto_select: false,
      callback: ({ credential }) => credentialResult?.(acceptStaffCredential(credential)),
    });
    gisInitialized = true;
  }
  identity.renderButton(element, { type: "standard", theme: "outline", size: "large" });
}
