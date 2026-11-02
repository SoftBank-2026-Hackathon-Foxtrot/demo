import { CheckCircle, HourglassMedium, XCircle } from "@phosphor-icons/react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { getReceipt, type Order, type OrderStatus, type Receipt } from "./api";
import { won } from "./GoodsList";

const STATUS: Record<OrderStatus, { label: string; Glyph: typeof CheckCircle; tone: string }> = {
  QUEUED: { label: "확인하고 있어요", Glyph: HourglassMedium, tone: "text-muted" },
  CONFIRMED: { label: "주문이 확정됐어요", Glyph: CheckCircle, tone: "text-accent" },
  SOLD_OUT: { label: "품절되었거나 마감됐어요", Glyph: XCircle, tone: "text-muted" },
};

export function Orders({ sid, orders }: { sid: string; orders: Order[] | null }) {
  return (
    <section aria-labelledby="orders-title" className="mx-auto max-w-2xl px-4">
      <h2 id="orders-title" className="text-center font-display text-3xl text-brown">내 주문</h2>
      {!orders ? (
        <div aria-busy="true" className="mt-6 grid animate-pulse gap-3">
          <div className="h-20 rounded-2xl bg-tile" />
          <div className="h-20 rounded-2xl bg-tile" />
        </div>
      ) : orders.length === 0 ? (
        <p className="mt-6 rounded-2xl border-2 border-ink bg-surface p-8 text-center text-muted">아직 주문이 없어요. 마음에 드는 굿즈에 참여해 보세요.</p>
      ) : (
        <ul className="mt-6 grid gap-3" aria-live="polite">
          <AnimatePresence initial={false}>
            {orders.map((o) => <Row key={o.id} sid={sid} order={o} />)}
          </AnimatePresence>
        </ul>
      )}
    </section>
  );
}

function Row({ sid, order }: { sid: string; order: Order }) {
  const { label, Glyph, tone } = STATUS[order.status] ?? STATUS.QUEUED;
  const [receipt, setReceipt] = useState<Receipt | "loading" | "failed" | null>(null);

  async function open() {
    setReceipt("loading");
    try {
      setReceipt(await getReceipt(sid, order.id));
    } catch {
      setReceipt("failed");
    }
  }

  return (
    <motion.li
      layout="position"
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="rounded-2xl border-2 border-ink bg-surface p-4"
    >
      <div className="flex items-center gap-3">
        <Glyph size={28} weight="duotone" className={`shrink-0 ${tone} ${order.status === "QUEUED" ? "motion-safe:animate-pulse" : ""}`} />
        <div className="min-w-0 flex-1">
          <p className="leading-snug font-semibold">{order.title} {order.qty}개</p>
          <p className="mt-0.5 text-sm text-muted">{label}</p>
        </div>
        {order.status === "CONFIRMED" && (
          order.receipt ? (
            <button onClick={open} className="min-h-11 shrink-0 rounded-full border-2 border-ink px-4 text-sm font-semibold active:scale-[0.98]">영수증</button>
          ) : (
            <span className="shrink-0 text-sm text-muted">영수증 준비 중</span>
          )
        )}
      </div>
      {receipt === "loading" && <p className="mt-3 text-sm text-muted">영수증을 불러오고 있어요.</p>}
      {receipt === "failed" && <p role="alert" className="mt-3 text-sm font-medium text-accent">영수증을 불러오지 못했어요. 주문은 안전하게 확정됐어요.</p>}
      {receipt && typeof receipt === "object" && (
        <dl className="mt-3 grid grid-cols-2 gap-1 rounded-xl bg-canvas p-3 text-sm tabular-nums">
          <dt className="text-muted">단가</dt><dd className="text-right">{won(receipt.price)}</dd>
          <dt className="text-muted">수량</dt><dd className="text-right">{receipt.qty}개</dd>
          <dt className="font-semibold">합계</dt><dd className="text-right font-bold">{won(receipt.total)}</dd>
        </dl>
      )}
    </motion.li>
  );
}
