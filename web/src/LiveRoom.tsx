import { ArrowRight, ArrowUp, ChatCircleDots, Heart, Pause, Play, ShoppingBag, Sparkle, TelevisionSimple } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { GroupBuy } from "./api";
import { isOpen, Tile, won } from "./GoodsList";
import { useChat } from "./useChat";

export function LiveRoom({ sid, name, goods, onPick, onSessionLost }: {
  sid: string; name: string | null; goods: GroupBuy[]; onPick: (g: GroupBuy) => void; onSessionLost: () => void;
}) {
  const item = goods[0];
  const chat = useChat(sid, onSessionLost);
  const [draft, setDraft] = useState("");
  const [liked, setLiked] = useState(false);
  const [dancing, setDancing] = useState(true);
  const scroll = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const [tab, setTab] = useState<"chat" | "goods">("chat");

  useEffect(() => {
    if (nearBottom.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [chat.messages]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (text && !chat.pending && chat.send(text)) setDraft("");
  }

  return (
    <section className="live-section" aria-labelledby="live-title">
      <div className="live-heading">
        <div><span className="eyebrow"><span className="live-dot" /> CHIIKAWA LIVE</span>
          <h1 id="live-title">오늘도, 같이 모아요<span className="heading-star">✳</span></h1>
          <p>좋아하는 마음이 모이는 곳. 수다 떨며 굿즈 구경해요.</p></div>
        <span className="edition">G O O D S &nbsp; C L U B <span>VOL. 01 / 친구들 모여라!</span></span>
      </div>
      <div className="broadcast-layout">
        <div className="broadcast-main">
          <div className={`broadcast-stage ${dancing ? "is-dancing" : "dance-paused"}`}>
            <img src="/live-stage.png" alt="분홍 커튼과 별 장식이 있는 작은 방송 무대" />
            <div className="dancing-friends" aria-label="치이카와와 친구들의 댄스 무대">
              <div className="dancer hachiware"><span role="img" aria-label="춤추는 하치와레" /></div>
              <div className="dancer chiikawa"><span role="img" aria-label="춤추는 치이카와" /></div>
              <div className="dancer usagi"><span role="img" aria-label="춤추는 우사기" /></div>
            </div>
            <div className="dance-notes" aria-hidden="true"><span>♪</span><span>♫</span><span>♪</span></div>
            <div className="stage-top"><span className="on-air"><span /> ON AIR</span><span className="demo-tag">데모 방송</span></div>
            <div className="stage-sticker">작고 소중한<br /><strong>오늘의 친구들</strong><span>모두 함께 만나봐요 ♡</span></div>
            <button className="dance-toggle" aria-pressed={dancing} onClick={() => setDancing(!dancing)} aria-label={dancing ? "친구들 춤 멈추기" : "친구들 춤추기"}>{dancing ? <Pause size={13} weight="fill" /> : <Play size={13} weight="fill" />}<span>{dancing ? "댄스 타임" : "다시 춤추기"}</span></button>
            <button className={`stage-heart ${liked ? "is-liked" : ""}`} onClick={() => setLiked(!liked)} aria-label={liked ? "방송 좋아요 취소" : "방송 좋아요"} aria-pressed={liked}><Heart size={24} weight={liked ? "fill" : "regular"} /></button>
            <div className="stage-caption"><span><TelevisionSimple size={18} /> 치이카와의 작은 공구방</span><span>함께하면 더 귀여워!</span></div>
          </div>
          <div className="host-line"><div className="host-avatar"><Sparkle size={22} weight="fill" /></div><div><strong>치이카와의 작은 공구방</strong><p>오늘의 픽은? 포근한 봉제 인형과 친구들</p></div><span className="host-badge">공구지기</span></div>
          {item && <div className="featured-buy"><div className="product-number">01</div><Tile id={item.id} size={36} className="featured-tile" /><div className="featured-copy"><span>지금 만나고 있는 굿즈</span><h2>{item.title}</h2><p>{won(item.price)} <small>· 남은 수량 {item.stock.toLocaleString()}개</small></p></div><button disabled={!isOpen(item)} onClick={() => onPick(item)} className="buy-button"><ShoppingBag size={19} />{isOpen(item) ? "공구 참여" : "마감된 공구"}<ArrowRight size={18} /></button></div>}
        </div>
        <aside className="chat-panel" aria-label="라이브 채팅">
          <div className="chat-tabs"><button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}><ChatCircleDots size={18} />실시간 채팅</button><button className={tab === "goods" ? "active" : ""} onClick={() => setTab("goods")}><ShoppingBag size={18} />방송 상품 <span>{goods.length}</span></button></div>
          {tab === "chat" ? <>
            <div className="chat-status"><span className={`connection-dot ${chat.status === "connected" ? "online" : ""}`} />{chat.status === "connected" ? "같은 방송을 보며 이야기하고 있어요" : chat.status === "connecting" ? "채팅방에 입장하는 중이에요" : "연결이 잠시 끊겼어요. 다시 연결하고 있어요"}</div>
            <div className="chat-messages" ref={scroll} onScroll={() => { const el = scroll.current; if (el) nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 70; }} role="log" aria-label="채팅 메시지" aria-live="polite" aria-relevant="additions">
              <div className="chat-welcome"><span>✦</span><strong>작은 공구방에 오신 걸 환영해요!</strong><p>지금 눈여겨보는 굿즈가 있나요?<br />친구들과 첫 이야기를 나눠 보세요.</p></div>
              <div className="pinned-message"><span>공구지기</span>닉네임으로 편하게 이야기해요. 실제 결제와 배송은 없는 데모예요.</div>
              {chat.messages.map((m) => <div className={`chat-message ${m.user === name ? "mine" : ""}`} key={m.id}><span className="chat-avatar" style={{ background: avatarColor(m.user) }}>{m.user.slice(0, 1)}</span><div><div className="message-meta"><strong>{m.user}</strong>{m.user === name && <span>나</span>}<time dateTime={new Date(m.at).toISOString()}>{new Date(m.at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false })}</time></div><p>{m.text}</p></div></div>)}
            </div>
            <form onSubmit={submit} className="chat-composer"><label htmlFor="live-message">{name || "친구"}님, 한마디 남겨볼까요?</label><div className="composer-input"><textarea id="live-message" rows={2} value={draft} maxLength={300} placeholder="이 친구, 너무 귀엽지 않나요?" disabled={chat.status !== "connected"} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} /><button aria-label="메시지 보내기" disabled={!draft.trim() || chat.status !== "connected" || !!chat.pending}><ArrowUp size={21} weight="bold" /></button></div><div className="composer-footer"><span>서로에게 다정한 말을 건네 주세요 ♡</span><span>{draft.length}/300</span></div>
              {chat.pending && !chat.error && <p className="chat-feedback" role="status">메시지를 전달하고 있어요…</p>}
              {chat.error && <p className="chat-feedback error" role="alert">{chat.error} {chat.pending && <><button type="button" disabled={chat.status !== "connected"} onClick={() => chat.send(chat.pending!.text, chat.pending!.id)}>다시 보내기</button>{" · "}<button type="button" onClick={() => { setDraft(chat.pending!.text); chat.editPending(); }}>수정하기</button></>}</p>}
            </form>
          </> : <div className="broadcast-products">{goods.map((g, i) => <button key={g.id} disabled={!isOpen(g)} onClick={() => onPick(g)}><span className="list-index">{String(i + 1).padStart(2, "0")}</span><Tile id={g.id} size={30} className="size-14 bg-tile" /><span><strong>{g.title}</strong><small>{won(g.price)}</small></span><ArrowRight size={16} /></button>)}</div>}
        </aside>
      </div>
      <div className="live-footnote"><span><span className="tiny-star">✳</span> 같은 취향의 친구들과 함께하는 작은 즐거움</span><details><summary>연결 정보</summary><div className="connection-info">앱: {chat.info.server || "연결 중"}<br />연결 ID: {chat.info.connection || "—"}<br />재연결 {chat.info.reconnects}회 · 실시간 수신 {chat.info.received}건<br />최근 기록은 재접속 시 복원돼요.</div></details></div>
    </section>
  );
}

function avatarColor(name: string) {
  return ["#f9e0dc", "#dcebe5", "#e0e8f7", "#faedc9"][Array.from(name).reduce((a, c) => a + c.charCodeAt(0), 0) % 4];
}
