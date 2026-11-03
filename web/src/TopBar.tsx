import { CaretLeft, CaretRight, MagnifyingGlass, PawPrint, ShoppingCart, SignIn, SignOut, WarningCircle } from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";

const NOTICES = ["작고 귀여운 마음이 모이는 곳, 치이카와 LIVE", "오늘의 친구들을 라이브 공구방에서 만나보세요", "한 번에 5개까지, 좋아하는 친구와 함께해요"];

export function Announcement() {
  const [i, setI] = useState(0);
  const move = (d: number) => setI((i + d + NOTICES.length) % NOTICES.length);
  return (
    <div className="flex h-9 items-center justify-between bg-bar px-2 text-sm font-medium text-ink md:px-[16%]">
      <button aria-label="이전 안내" onClick={() => move(-1)} className="grid size-9 place-items-center rounded-full"><CaretLeft size={16} /></button>
      <p aria-live="polite" className="truncate">{NOTICES[i]}</p>
      <button aria-label="다음 안내" onClick={() => move(1)} className="grid size-9 place-items-center rounded-full"><CaretRight size={16} /></button>
    </div>
  );
}

export function Brand({ className = "" }: { className?: string }) {
  return (
    <span className={`flex items-center gap-2 font-display text-brown ${className}`}>
      <span className="grid size-13 place-items-center rounded-full border-2 border-accent bg-surface text-accent md:size-16">
        <PawPrint size={32} weight="fill" />
      </span>
      <span className="text-2xl md:text-[32px]">치이카와 <span className="brand-live">LIVE</span></span>
    </span>
  );
}

function Circle({ label, tint, onClick, badge, children }: { label: string; tint: string; onClick: () => void; badge?: number; children: ReactNode }) {
  return (
    <button onClick={onClick} className={`relative flex size-14 flex-col items-center justify-center rounded-full ${tint} text-ink transition hover:-translate-y-0.5 active:scale-[0.96]`}>
      {children}
      <span className="text-[11px] leading-tight font-semibold">{label}</span>
      {badge ? <span className="absolute -top-1 -right-1 grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1 text-xs font-bold text-on-accent">{badge}</span> : null}
    </button>
  );
}

type View = "live" | "all" | "closing" | "orders";

export function Header({ name, count, onCart, onLogout }: { name: string | null; count: number; onCart?: () => void; onLogout?: () => void }) {
  return (
    <header className="stripes">
      <div className="mx-auto grid max-w-[1320px] grid-cols-[1fr_auto] items-center gap-x-3 gap-y-2 px-4 py-3 md:min-h-25 md:grid-cols-[1fr_auto_1fr]">
        <p className="col-span-2 row-start-2 w-fit justify-self-center rounded-full border border-ink bg-surface px-8 py-1 text-sm md:col-span-1 md:row-start-1 md:justify-self-end md:mr-10">
          안녕하세요! {name ? `${name}님` : "게스트님"}
        </p>
        <Brand />
        {onCart && onLogout ? (
          <div className="flex justify-end gap-2">
            <Circle label="내 주문" tint="bg-mint" badge={count} onClick={onCart}><ShoppingCart size={22} weight="duotone" /></Circle>
            <Circle label="로그아웃" tint="bg-lemon" onClick={onLogout}><SignOut size={20} weight="duotone" /></Circle>
          </div>
        ) : (
          <div className="flex justify-end"><span className="flex size-14 flex-col items-center justify-center rounded-full bg-lemon"><SignIn size={20} weight="duotone" /><span className="text-[11px] font-semibold">Login</span></span></div>
        )}
      </div>
    </header>
  );
}

export function NavBar({ view, query, onView, onQuery }: { view: View; query: string; onView: (v: View) => void; onQuery: (q: string) => void }) {
  const items: [View, string][] = [["live", "라이브 공구방"], ["all", "전체 상품"], ["closing", "마감 임박"], ["orders", "내 주문"]];
  return (
    <nav className="bg-nav">
      <div className="mx-auto flex max-w-[1320px] flex-wrap items-center justify-center gap-x-8 gap-y-1 px-4 py-2 md:min-h-11">
        <ul className="flex items-center">
          {items.map(([v, label], i) => (
            <li key={v} className={i ? "border-l border-ink" : ""}>
              <button onClick={() => onView(v)} aria-current={view === v ? "page" : undefined} className={`min-h-9 px-4 text-[15px] hover:underline ${view === v ? "font-bold underline underline-offset-4" : ""}`}>
                {label}
              </button>
            </li>
          ))}
        </ul>
        <label className="flex w-full max-w-50 items-center border-b border-ink">
          <span className="sr-only">상품 찾기</span>
          <input value={query} onChange={(e) => onQuery(e.target.value)} placeholder="상품 찾기" className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted" />
          <MagnifyingGlass size={18} />
        </label>
      </div>
    </nav>
  );
}

export function DemoNotice() {
  return (
    <p className="px-4 pt-8 pb-6 text-center font-display text-lg text-[#d10a1e] underline underline-offset-4">
      ※ 시연용 데모입니다. 공식 스토어가 아니며 실제 결제와 배송은 없습니다 ※
    </p>
  );
}

export function Connection() {
  return (
    <p role="status" className="flex items-center justify-center gap-2 bg-accent-soft px-4 py-2 text-sm font-medium">
      <WarningCircle size={18} className="shrink-0 text-accent" />
      연결이 잠시 불안정해요. 자동으로 다시 시도하고 있어요.
    </p>
  );
}

export type { View };
