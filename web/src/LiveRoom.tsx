import { ArrowRight, ArrowUp, ChatCircleDots, Heart, Pause, Play, ShoppingBag } from "@phosphor-icons/react";
import { useState, type FormEvent } from "react";
import type { GroupBuy } from "./api";
import { isOpen, Tile, won } from "./GoodsList";
import { useChat } from "./useChat";
import { MigrationStatus } from "./MigrationStatus";
import { FloatingChat } from "./FloatingChat";

export function LiveRoom({ sid, name, goods, onPick, onSessionLost }: {
  sid: string; name: string | null; goods: GroupBuy[]; onPick: (g: GroupBuy) => void; onSessionLost: () => void;
}) {
  const item = goods[0];
  const chat = useChat(sid, onSessionLost);
  const [draft, setDraft] = useState("");
  const [botRate, setBotRate] = useState("10");
  const validBotRate = Number.isInteger(Number(botRate)) && Number(botRate) >= 1 && Number(botRate) <= 1000;
  const [liked, setLiked] = useState(false);
  const [dancing, setDancing] = useState(true);

  function submit(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (text && !chat.pending && chat.send(text)) setDraft("");
  }

  return (
    <section className="live-section" aria-labelledby="live-title">
      <h1 id="live-title" className="sr-only">라이브 공구</h1>
      <MigrationStatus sid={sid} since={chat.measuredSince} liveIds={chat.liveIds} chatEnvironment={chat.info.environment} connected={chat.status === "connected"} onSessionLost={onSessionLost} />
      <div className="chat-bot-controls live-traffic-controls"><div className="chat-bot-row"><button type="button" className={`chat-bot-toggle ${chat.bot.rate?"running":""}`} aria-pressed={chat.bot.rate>0} disabled={chat.status!=="connected"||(!chat.bot.rate&&!validBotRate)} onClick={()=>chat.setBotRate(chat.bot.rate?0:Number(botRate))}>{chat.bot.rate?<Pause size={14}/>:<Play size={14}/>} {chat.bot.rate?"봇 정지":"채팅 봇 시작"}</button><label htmlFor="chat-bot-rate">트래픽</label><input id="chat-bot-rate" type="number" min={1} max={1000} step={1} value={botRate} aria-invalid={!validBotRate} onChange={e=>{setBotRate(e.target.value);const rate=Number(e.target.value);if(chat.bot.rate&&Number.isInteger(rate)&&rate>=1&&rate<=1000)chat.setBotRate(rate);}}/><span>개/초</span></div><p className={chat.bot.rate||!validBotRate?"":"sr-only"} role="status">{!validBotRate?"초당 1~1,000개로 입력해 주세요.":chat.bot.rate?`실행 중 · 목표 ${chat.bot.rate.toLocaleString()}개/초 · 이 화면을 닫으면 정지`:"자동 채팅 대기 중"}</p>{chat.bot.error&&<p className="error" role="alert">{chat.bot.error}</p>}</div>
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
            <button className="dance-toggle" aria-pressed={dancing} onClick={() => setDancing(!dancing)} aria-label={dancing ? "친구들 춤 멈추기" : "친구들 춤추기"}>{dancing ? <Pause size={13} weight="fill" /> : <Play size={13} weight="fill" />}<span>{dancing ? "댄스 타임" : "다시 춤추기"}</span></button>
            <button className={`stage-heart ${liked ? "is-liked" : ""}`} onClick={() => setLiked(!liked)} aria-label={liked ? "방송 좋아요 취소" : "방송 좋아요"} aria-pressed={liked}><Heart size={24} weight={liked ? "fill" : "regular"} /></button>
            <FloatingChat messages={chat.messages} liveIds={chat.liveIds.current}/>
            <form onSubmit={submit} className="stage-composer"><label htmlFor="live-message" className="sr-only">채팅 입력</label><div className="composer-input"><textarea id="live-message" rows={1} value={draft} maxLength={300} placeholder={chat.status==="connected"?"채팅으로 함께해요…":"채팅 재연결 중…"} disabled={chat.status !== "connected"} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form?.requestSubmit();}}}/><button aria-label="메시지 보내기" disabled={!draft.trim()||chat.status!=="connected"||!!chat.pending}><ArrowUp size={20} weight="bold"/></button></div>{chat.pending&&!chat.error&&<p className="stage-chat-feedback" role="status">메시지를 전달하고 있어요…</p>}{chat.error&&<p className="stage-chat-feedback" role="alert">{chat.error}{chat.pending&&<><button type="button" disabled={chat.status!=="connected"} onClick={()=>chat.send(chat.pending!.text,chat.pending!.id)}>다시 보내기</button><button type="button" onClick={()=>{setDraft(chat.pending!.text);chat.editPending();}}>수정하기</button></>}</p>}</form>
          </div>
          {item && <div className="featured-buy"><div className="product-number">01</div><Tile id={item.id} size={36} className="featured-tile" /><div className="featured-copy"><span>지금 만나고 있는 굿즈</span><h2>{item.title}</h2><p>{won(item.price)} <small>· 남은 수량 {item.stock.toLocaleString()}개</small></p></div><button disabled={!isOpen(item)} onClick={() => onPick(item)} className="buy-button"><ShoppingBag size={19} />{isOpen(item) ? "공구 참여" : "마감된 공구"}<ArrowRight size={18} /></button></div>}
        </div>

      </div>
      <details className="live-tools"><summary><ChatCircleDots size={15}/><span className={chat.status==="connected"?"online-label":""}>{chat.status==="connected"?"채팅 연결됨":chat.status==="connecting"?"채팅 연결 중":"채팅 재연결 중"}</span><span>채팅 기록</span></summary><div className="chat-history" role="log" aria-label="채팅 전체 기록" aria-live="polite">{chat.messages.length===0&&<p>아직 메시지가 없습니다.</p>}{chat.messages.map(m=><div key={m.id}><strong>{m.user}{m.user===name?" (나)":""}</strong><span>{m.text}</span></div>)}</div></details>
      <div className="live-footnote"><details><summary>연결 정보</summary><div className="connection-info">앱: {chat.info.server || "연결 중"}<br />연결 ID: {chat.info.connection || "—"}<br />재연결 {chat.info.reconnects}회 · 실시간 수신 {chat.info.received}건</div></details></div>
    </section>
  );
}
