import { createPortal } from "react-dom";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play } from "@phosphor-icons/react";
import { ApiError, join, listOrders, newOrderKey, prepareOrderDemo, readOrderPulse, sendOrderBatch, startOrderDemo, SessionLost, type OrderPulse as Snapshot } from "./api";
import "./order-pulse.css";
import { JoinQr } from "./LiveEffects";

function savedProduct(key: string) {
  try { const id = Number(new URLSearchParams(window.location.search).get("order_product") || sessionStorage.getItem(key)); return Number.isInteger(id) && id >= 9000001 && id <= 2147483647 ? id : undefined; }
  catch { return undefined; }
}
function failure(error: unknown) {
  if (error instanceof ApiError && error.status === 404) {
    if (error.detail.includes("disabled")) return "서버에 ENABLE_ORDER_DEMO=1 설정이 필요해요.";
    if (error.detail === "Not Found") return "서버에 주문 시연 API가 배포되지 않았어요.";
  }
  return "주문 현황을 불러오지 못했어요. 다시 확인 중이에요.";
}
export function OrderPulse({ sid, onSessionLost, settingsTarget }: { sid: string; onSessionLost: () => void; settingsTarget?:HTMLElement|null }) {
  const storageKey = `order-demo-product:${sid}`;
  const product = useRef(savedProduct(storageKey));
  const revision = useRef(0);
  const alive = useRef(true);
  const [data, setData] = useState<Snapshot | null>(null);
  const [running, setRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [rate, setRate] = useState("10");
  const [stock, setStock] = useState("1000");
  const edited = useRef(false);
  const [pollError, setPollError] = useState("");
  const [unavailable, setUnavailable] = useState(false);
  const [sendError, setSendError] = useState("");
  const [buying, setBuying] = useState(false);
  const [personalOrder, setPersonalOrder] = useState<string | null>(null);
  const [buyStatus, setBuyStatus] = useState("");
  const manual = useRef<{key:string;productId:number} | null>(null);
  const buyingNow = useRef(false);
  const active = useRef(false);
  const count = useRef(10);
  const batch = useRef<{ count: number; key: string; productId?: number } | null>(null);
  const setup = useRef<{ stock: number; key: string } | null>(null);
  const validRate = Number.isInteger(Number(rate)) && Number(rate) >= 1 && Number(rate) <= 100;
  const validStock = Number.isInteger(Number(stock)) && Number(stock) >= 1 && Number(stock) <= 1_000_000;
  count.current = validRate ? Number(rate) : 10;
  const stopOrders=useCallback(()=>{active.current=false;setRunning(false);},[]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (!personalOrder) return;
    const requestId = personalOrder;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function check() {
      try {
        const order = (await listOrders(sid, requestId)).find(item => item.id === requestId);
        if (stopped) return;
        if (order && order.status !== "QUEUED") {
          setBuyStatus(order.status === "CONFIRMED" ? "주문 확정" : "품절로 주문되지 않았어요.");
          setPersonalOrder(null);
          return;
        }
      } catch (error) { if (!stopped && error instanceof SessionLost) { onSessionLost(); return; } }
      if (!stopped) timer = setTimeout(check, 1000);
    }
    void check();
    return () => { stopped = true; clearTimeout(timer); };
  }, [personalOrder, sid, onSessionLost]);
  async function buyOne() {
    if (buyingNow.current || personalOrder || !data || pollError || unavailable || (data.stock <= 0 && !manual.current)) return;
    buyingNow.current = true; setBuying(true); setBuyStatus("");
    const pending = manual.current ?? {key:newOrderKey(),productId:data.product_id};
    manual.current = pending;
    try {
      const result = await join(sid, pending.productId, 1, pending.key);
      manual.current = null;
      if (alive.current) { setPersonalOrder(result.request_id); setBuyStatus("내 주문 접수 · 처리 중"); }
    } catch (error) {
      if (alive.current) {
        if (error instanceof SessionLost) onSessionLost();
        else setBuyStatus(error instanceof ApiError && error.status === 429 ? "잠시 후 다시 눌러 주세요." : "주문 확인이 필요해요. 다시 누르면 같은 주문으로 확인해요.");
      }
    } finally { buyingNow.current = false; if (alive.current) setBuying(false); }
  }
  useEffect(() => {
    let stopped = false;
    let initialized = product.current !== undefined;
    let timer: ReturnType<typeof setTimeout>;
    let request: AbortController | null = null;
    async function poll() {
      if (document.hidden) { timer = setTimeout(poll, 1000); return; }
      request = new AbortController();
      const version = revision.current;
      const deadline = setTimeout(() => request?.abort(), 8000);
      let delay = 1000;
      try {
        const next = await (initialized ? readOrderPulse(sid, request.signal, product.current) : prepareOrderDemo(sid, request.signal));
        initialized = true;
        if (!stopped && version === revision.current) {
          setData(next); setPollError(""); setUnavailable(false);
          if (!edited.current) setStock(String(next.stock));
          if (next.stock === 0) { active.current = false; setRunning(false); }
        }
      } catch (error) {
        if (!stopped && version === revision.current) {
          if (error instanceof SessionLost) onSessionLost();
          else {
            const disabled = error instanceof ApiError && error.status === 404 && (error.detail.includes("disabled") || error.detail === "Not Found");
            setUnavailable(disabled); setPollError(failure(error)); if (disabled) delay = 5000;
          }
        }
      } finally { clearTimeout(deadline); if (!stopped) timer = setTimeout(poll, delay); }
    }
    void poll();
    return () => { stopped = true; clearTimeout(timer); request?.abort(); };
  }, [sid, onSessionLost]);
  useEffect(() => {
    const visibility = () => { if (document.hidden) { active.current = false; setRunning(false); } };
    document.addEventListener("visibilitychange", visibility);
    return () => document.removeEventListener("visibilitychange", visibility);
  }, []);
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function tick() {
      if (active.current) {
        const pending = batch.current ?? { count: count.current, key: newOrderKey(), productId: product.current };
        batch.current = pending;
        try {
          await sendOrderBatch(sid, pending.count, pending.key, pending.productId);
          if (batch.current === pending) batch.current = null;
          if (!stopped) setSendError("");
        } catch (error) {
          if (!stopped) {
            if (error instanceof SessionLost) { active.current = false; setRunning(false); onSessionLost(); }
            else if (error instanceof ApiError && error.status >= 400 && error.status < 500) { active.current = false; setRunning(false); setSendError(error.status === 409 ? "주문 마감" : failure(error)); }
            else setSendError("주문 연결 대기 · 같은 요청 재시도 중");
          }
        }
      }
      if (!stopped) timer = setTimeout(tick, 1000);
    }
    void tick();
    return () => { stopped = true; active.current = false; clearTimeout(timer); };
  }, [sid, onSessionLost]);
  async function startOrders() {
    if (active.current) return;
    if (starting || unavailable || !validStock || !validRate) return;
    setStarting(true); setSendError("");
    try {
      if (edited.current || !data || data.stock === 0) {
        if (!setup.current || setup.current.stock !== Number(stock)) setup.current = { stock: Number(stock), key: newOrderKey() };
        revision.current += 1;
        const next = await startOrderDemo(sid, setup.current.stock, setup.current.key);
        if (!alive.current) return;
        revision.current += 1;
        product.current = next.product_id;
        try { sessionStorage.setItem(storageKey, String(next.product_id)); } catch { /* Optional reload persistence. */ }
        const address = new URL(window.location.href);
        address.searchParams.set("order_product", String(next.product_id));
        window.history.replaceState(null, "", address);
        batch.current = null; setup.current = null; edited.current = false;
        setData(next); setStock(String(next.stock)); setPollError("");
      }
      if (!document.hidden && alive.current) { active.current = true; setRunning(true); }
    } catch (error) {
      if (alive.current) { if (error instanceof SessionLost) onSessionLost(); else setSendError(failure(error)); }
    } finally { if (alive.current) setStarting(false); }
  }
  const number = (value: number | undefined) => pollError || value === undefined ? "—" : value.toLocaleString();
  return <section className="order-pulse" aria-label="실시간 주문 현황">
    <div className="order-pulse-heading"><div className="order-pulse-product"><strong>{data?.title ?? "주문"}</strong><span>{unavailable ? "설정 필요" : pollError ? "갱신 대기" : data ? `${data.confirmed_per_second.toFixed(1)}건/초` : "준비"}</span></div><JoinQr productId={data?.product_id}/></div>
    <dl className="order-counters">
      <div><dt>남은 재고</dt><dd>{number(data?.stock)}</dd></div>
      {[["접수된 참여", data?.accepted], ["확정 주문", data?.confirmed], ["처리 대기", data?.pending]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{number(value as number | undefined)}</dd></div>)}
    </dl>
    <div className="order-pulse-controls"><button type="button" className="order-buy-one" disabled={buying || !!personalOrder || starting || !data || !!pollError || unavailable || (data.stock <= 0 && !manual.current)} onClick={() => void buyOne()}>{buying ? "접수 중" : personalOrder ? "처리 중" : manual.current ? "주문 재확인" : data?.stock === 0 ? "품절" : "1개 주문 요청"}</button></div>
    {(buyStatus || !!data?.my_confirmed) && <p role="status" className="order-buy-status">{!!data?.my_confirmed && <strong>내 주문 {data.my_confirmed.toLocaleString()}개 확정</strong>}{buyStatus && buyStatus !== "주문 확정" && <span>{data?.my_confirmed ? " · " : ""}{buyStatus}</span>}</p>}
    {pollError && <p role="status" className="order-pulse-error">{pollError}</p>}
    {settingsTarget && createPortal(<div className="order-macro-settings">
      <label htmlFor="order-stock">시작 재고<input id="order-stock" aria-label="시작 재고" type="number" inputMode="numeric" min="1" max="1000000" value={stock} disabled={running || starting} aria-invalid={edited.current && !validStock} onChange={event=>{edited.current=true;setStock(event.target.value);}}/></label>
      <div className="order-pulse-controls"><button type="button" disabled={starting || running || !validStock || !validRate || unavailable} onClick={()=>void startOrders()}><Play size={13} weight="fill"/>{starting ? "준비 중" : running ? "주문 중" : "주문 시작"}</button><input id="order-rate" aria-label="초당 주문 목표 건수" type="number" min="1" max="100" value={rate} disabled={running || starting} onChange={event=>setRate(event.target.value)}/><span>건/초</span><button type="button" disabled={!running || starting} onClick={stopOrders}><Pause size={13}/>주문 정지</button></div>
      {(!validRate || (edited.current && !validStock) || sendError) && <p role="status" className="order-pulse-error">{!validRate ? "주문은 1~100건으로 입력해 주세요." : edited.current && !validStock ? "재고는 1~1,000,000개로 입력해 주세요." : sendError}</p>}
    </div>,settingsTarget)}
  </section>;
}
