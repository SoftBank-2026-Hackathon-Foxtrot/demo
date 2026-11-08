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
export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(`${status}`); }
}

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

async function call<T>(path: string, sid: string | null, method = "GET", extra: Record<string, string> = {}, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { ...extra };
  if (sid) headers["x-session"] = sid;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal });
  if (r.status === 401) throw new SessionLost();
  if (!r.ok) {
    const payload = await r.json().catch(() => null) as { detail?: unknown } | null;
    throw new ApiError(r.status, typeof payload?.detail === "string" ? payload.detail : "");
  }
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
export type BaselineIds = Record<"chat" | "orders" | "requests" | "goods", string[]>;
export type Baseline = { at: number; ids: BaselineIds; limit_per_table: number; served_by: string };
export type LiveMetrics = {
  at: number; served_by: string; chat_ids: string[]; chat_sample_limit: number; delivery_grace_ms: number;
  retention: Record<keyof BaselineIds, { retained: number; expected: number }> | null;
};
export const saveBaseline = (sid: string) => call<Baseline>("/live/baseline", sid);
export const readLiveMetrics = (sid: string, since: number, baseline: BaselineIds | null) =>
  call<LiveMetrics>("/live/metrics", sid, "POST", {}, { since_ms: since, baseline });
/** The same key on every retry of one order, so a lost response cannot order twice. */
export function newOrderKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

export const join = (sid: string, id: number, qty: number, key: string) =>
  call<{ request_id: string }>(`/groupbuys/${id}/join?qty=${qty}`, sid, "POST", { "Idempotency-Key": key });

export type OrderPulse = {stock:number;initial:number;title:string;accepted:number;confirmed:number;pending:number;sold_out:number;confirmed_qty:number;confirmed_per_second:number;at:number;product_id:number};
export const prepareOrderDemo = (sid:string,signal:AbortSignal)=>call<OrderPulse>("/live/orders/prepare",sid,"POST",{},undefined,signal);
export const readOrderPulse = (sid:string,signal:AbortSignal,productId?:number)=>call<OrderPulse>(`/live/orders${productId?`?product_id=${productId}`:""}`,sid,"GET",{},undefined,signal);
export const startOrderDemo = (sid:string,stock:number,key:string)=>call<OrderPulse>("/live/orders/prepare",sid,"POST",{"Idempotency-Key":key},{stock});
export const sendOrderBatch = (sid:string,count:number,key:string,productId?:number)=>call<{accepted:number}>("/live/orders",sid,"POST",{"Idempotency-Key":key},{count,...(productId?{product_id:productId}:{})});
