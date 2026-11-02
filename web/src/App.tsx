import { useCallback, useEffect, useState } from "react";
import { forgetSession, listGroupBuys, listOrders, logout, me, savedSession, SessionLost, type GroupBuy, type Order } from "./api";
import { Carousel, GoodsGrid, isClosing, Skeleton } from "./GoodsList";
import { JoinSheet } from "./JoinSheet";
import { Login } from "./Login";
import { Orders } from "./Orders";
import { Announcement, Connection, DemoNotice, Header, NavBar, type View } from "./TopBar";

const FEATURED = 5;

export function App() {
  const [sid, setSid] = useState<string | null>(savedSession);
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    if (!sid) return;
    me(sid)
      .then(({ uid }) => setName(uid))
      .catch((e) => {
        if (e instanceof SessionLost) {
          forgetSession();
          setSid(null);
        }
      });
  }, [sid]);

  if (!sid) return <Login onDone={(s, n) => { setName(n); setSid(s); }} />;
  return (
    <Shop
      key={sid}
      sid={sid}
      name={name}
      onLeave={() => { forgetSession(); setSid(null); setName(null); }}
      onLogout={() => { void logout(sid); setSid(null); setName(null); }}
    />
  );
}

function Shop({ sid, name, onLeave, onLogout }: { sid: string; name: string | null; onLeave: () => void; onLogout: () => void }) {
  const [goods, setGoods] = useState<GroupBuy[] | null>(null);
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [offline, setOffline] = useState(false);
  const [picked, setPicked] = useState<GroupBuy | null>(null);
  const [view, setView] = useState<View>("all");
  const [query, setQuery] = useState("");

  const fail = useCallback((e: unknown) => {
    if (e instanceof SessionLost) onLeave();
    else setOffline(true);
  }, [onLeave]);

  const refreshOrders = useCallback(async () => {
    try {
      setOrders(await listOrders(sid));
      setOffline(false);
    } catch (e) {
      fail(e);
    }
  }, [sid, fail]);

  const refreshGoods = useCallback(async () => {
    try {
      setGoods(await listGroupBuys(sid));
      setOffline(false);
    } catch (e) {
      fail(e);
    }
  }, [sid, fail]);

  useEffect(() => {
    void refreshGoods();
    const t = setInterval(refreshGoods, 5000);
    return () => clearInterval(t);
  }, [refreshGoods]);

  const waiting = orders?.some((o) => o.status === "QUEUED") ?? false;
  useEffect(() => {
    void refreshOrders();
    const t = setInterval(refreshOrders, waiting ? 1000 : 5000);
    return () => clearInterval(t);
  }, [refreshOrders, waiting]);

  const q = query.trim().toLowerCase();
  const searching = q.length > 0;
  const found = (goods ?? []).filter((g) => !q || g.title.toLowerCase().includes(q));
  const shown = view === "closing" ? found.filter((g) => isClosing(g)) : found;

  return (
    <div className="min-h-[100dvh]">
      <Announcement />
      <Header name={name} count={orders?.length ?? 0} onCart={() => setView("orders")} onLogout={onLogout} />
      <NavBar view={view} query={query} onView={setView} onQuery={(v) => { setQuery(v); if (view === "orders") setView("all"); }} />
      {offline && <Connection />}
      <DemoNotice />
      <main className="pb-16">
        {view === "orders" ? (
          <Orders sid={sid} orders={orders} />
        ) : !goods ? (
          <Skeleton />
        ) : view === "closing" || searching ? (
          <GoodsGrid goods={shown} title={view === "closing" ? "마감 임박" : "검색 결과"} onPick={setPicked} />
        ) : (
          <div className="flex flex-col gap-12">
            <Carousel items={goods.slice(0, FEATURED)} onPick={setPicked} />
            {goods.length > FEATURED && <GoodsGrid goods={goods.slice(FEATURED)} title="전체 상품" onPick={setPicked} />}
          </div>
        )}
      </main>
      <JoinSheet
        sid={sid}
        item={picked}
        onClose={() => setPicked(null)}
        onSessionLost={onLeave}
        onJoined={() => {
          setPicked(null);
          setView("orders");
          void refreshOrders();
          void refreshGoods();
        }}
      />
    </div>
  );
}
