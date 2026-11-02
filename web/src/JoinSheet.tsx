import { Minus, Plus, X } from "@phosphor-icons/react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { getGroupBuy, join, newOrderKey, SessionLost, type GroupBuy } from "./api";
import { Tile, won } from "./GoodsList";

const MAX_QTY = 5;

type Props = {
  sid: string;
  item: GroupBuy | null;
  onClose: () => void;
  onJoined: () => void;
  onSessionLost: () => void;
};

export function JoinSheet({ item, ...rest }: Props) {
  return (
    <AnimatePresence>
      {item && <Sheet key={item.id} item={item} {...rest} />}
    </AnimatePresence>
  );
}

function Sheet({ sid, item, onClose, onJoined, onSessionLost }: Props & { item: GroupBuy }) {
  const [qty, setQty] = useState(1);
  const [price, setPrice] = useState(item.price);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const orderKey = useRef(newOrderKey());

  useEffect(() => {
    // The price the buyer confirms comes through the cache, like the app's detail page.
    let live = true;
    getGroupBuy(sid, item.id).then((d) => { if (live) setPrice(d.price); }).catch(() => undefined);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", onKey);
    return () => { live = false; removeEventListener("keydown", onKey); };
  }, [sid, item.id, onClose]);

  function changeQty(next: number) {
    setQty(next);
    orderKey.current = newOrderKey();     // a different order, not a retry
  }

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await join(sid, item.id, qty, orderKey.current);
      onJoined();
    } catch (e) {
      if (e instanceof SessionLost) onSessionLost();
      else {
        setError("주문을 접수하지 못했어요. 다시 눌러 주세요.");
        setBusy(false);
      }
    }
  }

  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center md:items-center" role="dialog" aria-modal="true" aria-label={`${item.title} 참여`}>
      <motion.div
        className="absolute inset-0 bg-ink/40"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      />
      <motion.div
        className="relative w-full max-w-md rounded-t-2xl border-2 border-ink bg-surface p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] md:rounded-2xl"
        initial={{ y: 40, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 40, opacity: 0 }}
        transition={{ type: "spring", stiffness: 380, damping: 34 }}
      >
        <div className="flex items-start gap-4">
          <Tile id={item.id} size={36} className="size-18 shrink-0 bg-tile" />
          <div className="min-w-0 flex-1">
            <h2 className="text-lg leading-snug font-bold">{item.title}</h2>
            <p className="mt-1 font-semibold tabular-nums">{won(price)}</p>
          </div>
          <button onClick={onClose} aria-label="닫기" className="-m-2 grid size-11 shrink-0 place-items-center rounded-full text-muted active:scale-[0.96]">
            <X size={20} />
          </button>
        </div>

        <div className="mt-6 flex items-center justify-between">
          <span id="qty-label" className="font-semibold">수량</span>
          <div role="group" aria-labelledby="qty-label" className="flex items-center gap-3">
            <Step label="수량 줄이기" disabled={qty <= 1} onClick={() => changeQty(qty - 1)}><Minus size={18} /></Step>
            <output aria-live="polite" className="w-7 text-center text-lg font-bold tabular-nums">{qty}</output>
            <Step label="수량 늘리기" disabled={qty >= Math.min(MAX_QTY, item.stock)} onClick={() => changeQty(qty + 1)}><Plus size={18} /></Step>
          </div>
        </div>

        {error && <p role="alert" className="mt-4 text-sm font-medium text-accent">{error}</p>}
        <button
          onClick={submit}
          disabled={busy}
          className="mt-6 h-13 w-full rounded-full border-2 border-ink bg-accent font-bold text-on-accent tabular-nums transition active:scale-[0.98] disabled:opacity-60"
        >
          {busy ? "접수하는 중" : `${won(price * qty)} 참여하기`}
        </button>
      </motion.div>
    </div>
  );
}

function Step({ label, disabled, onClick, children }: { label: string; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="grid size-11 place-items-center rounded-full border-2 border-ink transition active:scale-[0.96] disabled:opacity-40"
    >
      {children}
    </button>
  );
}
