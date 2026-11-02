export type GroupBuy = {
  id: number;
  title: string;
  price: number;
  stock: number;
  closed: boolean;
  close_at_ms: number;
};

export type OrderStatus = "QUEUED" | "CONFIRMED" | "SOLD_OUT";

export type Order = {
  id: string;
  title: string;
  qty: number;
  status: OrderStatus;
  created_ms: number;
  receipt: boolean;
};

export type Receipt = {
  title: string;
  price: number;
  qty: number;
  total: number;
};

export class SessionLost extends Error {}

const SESSION_KEY = "groupbuy-session";

export function savedSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function saveSession(sid: string | null) {
  try {
    if (sid) localStorage.setItem(SESSION_KEY, sid);
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    // private mode: the session lasts until the tab closes
  }
}

async function call<T>(path: string, sid: string | null, method = "GET", extra: Record<string, string> = {}): Promise<T> {
  const headers: Record<string, string> = { ...extra };
  if (sid) headers["x-session"] = sid;
  const r = await fetch(`/api${path}`, { method, headers });
  if (r.status === 401) throw new SessionLost();
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json() as Promise<T>;
}

export async function login(name: string): Promise<string> {
  const { sid } = await call<{ sid: string }>(`/login/${encodeURIComponent(name)}`, null, "POST");
  saveSession(sid);
  return sid;
}

export async function logout(sid: string) {
  saveSession(null);
  await call("/logout", sid, "POST").catch(() => undefined);
}

export function forgetSession() {
  saveSession(null);
}

export const me = (sid: string) => call<{ uid: string }>("/me", sid);
export const listGroupBuys = (sid: string) => call<GroupBuy[]>("/groupbuys", sid);
export const listOrders = (sid: string) => call<Order[]>("/me/requests", sid);
export const getReceipt = (sid: string, id: string) => call<Receipt>(`/me/receipts/${id}`, sid);
export const getGroupBuy = (sid: string, id: number) => call<{ price: number }>(`/groupbuys/${id}`, sid);
/** The same key on every retry of one order, so a lost response cannot order twice. */
export function newOrderKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

export const join = (sid: string, id: number, qty: number, key: string) =>
  call<{ request_id: string }>(`/groupbuys/${id}/join?qty=${qty}`, sid, "POST", { "Idempotency-Key": key });
