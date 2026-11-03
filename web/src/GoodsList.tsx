import { Backpack, CaretLeft, CaretRight, Coffee, Cookie, Gift, Key, NotePencil, PawPrint, Star, Sticker, TShirt, type Icon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import type { GroupBuy } from "./api";

const ICONS: Icon[] = [PawPrint, Key, Coffee, Backpack, NotePencil, Sticker, Gift, Cookie, Star, TShirt];
const TINTS = ["bg-tile", "bg-lemon", "bg-mint"];
export const won = (n: number) => `${n.toLocaleString("ko-KR")}원`;
const CLOSING_MS = 10 * 60 * 1000;

export function isOpen(g: GroupBuy, now = Date.now()) {
  return !g.closed && g.stock > 0 && g.close_at_ms > now;
}

export function isClosing(g: GroupBuy, now = Date.now()) {
  return isOpen(g, now) && g.close_at_ms - now < CLOSING_MS;
}

function useNow() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function statusOf(g: GroupBuy, now: number) {
  if (g.stock <= 0) return "품절";
  const ms = g.close_at_ms - now;
  if (g.closed || ms <= 0) return "마감";
  if (ms >= 3_600_000) return `${Math.floor(ms / 3_600_000)}시간 뒤 마감`;
  const s = Math.ceil(ms / 1000);
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초 뒤 마감` : `${s}초 뒤 마감`;
}

/** Explicit image registry avoids requesting nonexistent photos for icon-only items. */
const GOODS_PHOTOS: Record<number, string> = { 0: "/live-studio.png" };
export function Tile({ id, size, className = "" }: { id: number; size: number; className?: string }) {
  const [broken, setBroken] = useState(false);
  const Glyph = ICONS[id % ICONS.length];
  return (
    <span className={`grid place-items-center overflow-hidden rounded-xl ${className}`}>
      {broken || !GOODS_PHOTOS[id] ? (
        <Glyph size={size} weight="duotone" className="text-accent" />
      ) : (
        <img src={GOODS_PHOTOS[id]} alt="" onError={() => setBroken(true)} className="size-full object-cover" />
      )}
    </span>
  );
}

export function Carousel({ items, onPick }: { items: GroupBuy[]; onPick: (g: GroupBuy) => void }) {
  const track = useRef<HTMLDivElement>(null);
  const now = useNow();
  const slide = (dir: number) => track.current?.scrollBy({ left: dir * track.current.clientWidth * 0.6, behavior: "smooth" });
  return (
    <section aria-label="추천 공구" className="relative">
      <div ref={track} className="no-scrollbar flex snap-x snap-mandatory gap-6 overflow-x-auto px-[max(1rem,calc(50vw-293px))] pb-2 lg:px-12">
        {items.map((g, i) => {
          const open = isOpen(g, now);
          return (
            <article key={g.id} className={`flex aspect-square w-[min(86vw,586px)] shrink-0 snap-center flex-col rounded-2xl border-2 border-ink p-5 md:p-8 ${TINTS[i % TINTS.length]}`}>
              <h2 className="font-display text-3xl leading-tight text-accent md:text-5xl">{g.title}</h2>
              <Tile id={g.id} size={140} className="my-3 min-h-0 w-full flex-1" />
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="font-display text-2xl md:text-3xl">{won(g.price)}</p>
                  <p className="mt-1 text-sm text-muted tabular-nums">{statusOf(g, now)}</p>
                </div>
                <button onClick={() => onPick(g)} disabled={!open} className="h-12 rounded-full border-2 border-ink bg-accent px-7 font-bold text-on-accent transition active:scale-[0.98] disabled:bg-surface disabled:text-muted">
                  참여하기
                </button>
              </div>
            </article>
          );
        })}
      </div>
      <Arrow label="이전 상품" side="left-3" onClick={() => slide(-1)}><CaretLeft size={20} weight="bold" /></Arrow>
      <Arrow label="다음 상품" side="right-3" onClick={() => slide(1)}><CaretRight size={20} weight="bold" /></Arrow>
    </section>
  );
}

function Arrow({ label, side, onClick, children }: { label: string; side: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button aria-label={label} onClick={onClick} className={`absolute top-1/2 ${side} hidden size-12 -translate-y-1/2 place-items-center rounded-full bg-surface/90 shadow-sm active:scale-[0.96] md:grid`}>
      {children}
    </button>
  );
}

export function GoodsGrid({ goods, title, onPick }: { goods: GroupBuy[]; title: string; onPick: (g: GroupBuy) => void }) {
  const now = useNow();
  return (
    <section className="mx-auto max-w-[1320px] px-4">
      <h2 className="text-center font-display text-3xl text-brown">{title}</h2>
      {goods.length === 0 ? (
        <p className="mx-auto mt-6 max-w-md rounded-2xl border-2 border-ink bg-surface p-8 text-center text-muted">찾는 상품이 없어요. 다른 이름으로 찾아보세요.</p>
      ) : (
        <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
          {goods.map((g, i) => (
            <button key={g.id} onClick={() => onPick(g)} disabled={!isOpen(g, now)} className="flex flex-col rounded-2xl border-2 border-ink bg-surface p-3 text-left transition hover:-translate-y-0.5 active:scale-[0.98] disabled:opacity-55">
              <Tile id={g.id} size={56} className={`aspect-square w-full ${TINTS[i % TINTS.length]}`} />
              <span className="mt-3 text-[15px] leading-snug font-semibold">{g.title}</span>
              <span className="mt-1 font-bold tabular-nums">{won(g.price)}</span>
              <span className="mt-0.5 text-[13px] text-muted tabular-nums">{statusOf(g, now)}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export function Skeleton() {
  return (
    <div aria-busy="true" aria-label="불러오는 중" className="flex animate-pulse justify-center gap-6 overflow-hidden px-4">
      {[0, 1, 2].map((i) => <div key={i} className="aspect-square w-[min(86vw,586px)] shrink-0 rounded-2xl bg-tile" />)}
    </div>
  );
}
