import { MagnifyingGlass, PawPrint, ShoppingCart, SignIn, SignOut, WarningCircle } from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";

export function Brand({ className = "", onLiveSettings }: { className?: string; onLiveSettings?: () => void }) {
  return (
    <span className={`flex items-center gap-2 font-display text-brown ${className}`}>
      <span className="grid size-13 place-items-center rounded-full border-2 border-accent bg-surface text-accent md:size-16">
        <PawPrint size={32} weight="fill" />
      </span>
      <span className="text-2xl md:text-[32px]">치이카와 {onLiveSettings ? <button type="button" className="brand-live" aria-label="LIVE 설정" aria-haspopup="dialog" onClick={onLiveSettings}>LIVE</button> : <span className="brand-live">LIVE</span>}</span>
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

export function Header({ name, count, onCart, onLogout, onLiveSettings }: { name: string | null; count: number; onCart?: () => void; onLogout?: () => void; onLiveSettings?: () => void }) {
  return (
    <header className="stripes">
      <div className="shop-topbar">
        <Brand onLiveSettings={onLiveSettings} />
        <p className="shop-greeting">{name ? `${name}님` : "게스트님"}</p>
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
  const [searchOpen, setSearchOpen] = useState(false);
  const items: [View, string][] = [["live", "라이브 공구방"], ["all", "전체 상품"], ["closing", "마감 임박"], ["orders", "내 주문"]];
  return (
    <nav className="bg-nav">
      <div className="shop-navigation">
        <ul className="flex items-center">
          {items.map(([v, label], i) => (
            <li key={v} className={i ? "border-l border-ink" : ""}>
              <button onClick={() => onView(v)} aria-current={view === v ? "page" : undefined} className={`min-h-9 px-4 text-[15px] hover:underline ${view === v ? "font-bold underline underline-offset-4" : ""}`}>
                {label}
              </button>
            </li>
          ))}
        </ul>
        <button className="mobile-search-toggle" aria-label="상품 검색 열기" aria-expanded={searchOpen} onClick={() => {setSearchOpen(!searchOpen); if(searchOpen) onQuery("");}}><MagnifyingGlass size={19}/></button>
        <label className={`shop-search ${searchOpen ? "is-open" : ""}`}>
          <span className="sr-only">상품 찾기</span>
          <input value={query} onChange={(e) => onQuery(e.target.value)} onKeyDown={e=>{if(e.key==="Escape"){setSearchOpen(false);onQuery("");}}} placeholder="상품 찾기" className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted" />
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
