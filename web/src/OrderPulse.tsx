import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "@phosphor-icons/react";
import { newOrderKey, prepareOrderDemo, readOrderPulse, sendOrderBatch, SessionLost, type OrderPulse as Snapshot } from "./api";
import "./order-pulse.css";

export function OrderPulse({sid,onSessionLost}:{sid:string;onSessionLost:()=>void}) {
  const [data,setData]=useState<Snapshot|null>(null);
  const [running,setRunning]=useState(false);
  const [rate,setRate]=useState("10");
  const [pollError,setPollError]=useState(false);
  const [sendError,setSendError]=useState("");
  const active=useRef(false);
  const count=useRef(10);
  const batch=useRef<{count:number;key:string}|null>(null);
  const valid=Number.isInteger(Number(rate))&&Number(rate)>=1&&Number(rate)<=100;
  count.current=valid?Number(rate):10;

  useEffect(()=>{
    let stopped=false;
    let initialized=false;
    let timer:ReturnType<typeof setTimeout>;
    let request:AbortController|null=null;
    async function poll(){
      if(document.hidden){timer=setTimeout(poll,1000);return;}
      request=new AbortController();
      const deadline=setTimeout(()=>request?.abort(),8000);
      try{
        const snapshot=await(initialized?readOrderPulse(sid,request.signal):prepareOrderDemo(sid,request.signal));
        initialized=true;
        if(!stopped){setData(snapshot);setPollError(false);if(snapshot.stock===0){active.current=false;setRunning(false);}}
      }catch(error){if(!stopped){setPollError(true);if(error instanceof SessionLost)onSessionLost();}}
      finally{clearTimeout(deadline);if(!stopped)timer=setTimeout(poll,1000);}
    }
    void poll();
    return ()=>{stopped=true;clearTimeout(timer);request?.abort();};
  },[sid,onSessionLost]);

  useEffect(()=>{
    const visibility=()=>{if(document.hidden){active.current=false;setRunning(false);}};
    document.addEventListener("visibilitychange",visibility);
    return()=>document.removeEventListener("visibilitychange",visibility);
  },[]);

  useEffect(()=>{
    let stopped=false;
    let timer:ReturnType<typeof setTimeout>;
    async function tick(){
      if(active.current){
        batch.current??={count:count.current,key:newOrderKey()};
        try{await sendOrderBatch(sid,batch.current.count,batch.current.key);batch.current=null;if(!stopped)setSendError("");}
        catch(error){if(!stopped){if(error instanceof SessionLost){active.current=false;setRunning(false);onSessionLost();}else if(error instanceof Error&&/^(409|4\d\d)$/.test(error.message)){active.current=false;setRunning(false);setSendError(error.message==="409"?"주문 마감":"주문 요청 실패");}else setSendError("주문 연결 대기 · 같은 요청 재시도 중");}}
      }
      if(!stopped)timer=setTimeout(tick,1000);
    }
    void tick();
    return ()=>{stopped=true;active.current=false;clearTimeout(timer);};
  },[sid,onSessionLost]);

  const number=(value:number|undefined)=>pollError||value===undefined?"—":value.toLocaleString();
  return <section className="order-pulse" aria-label="실시간 주문 현황">
    <div className="order-pulse-heading"><strong>{data?.title??"주문"}</strong><span>{pollError?"갱신 대기":data?`${data.confirmed_per_second.toFixed(1)}건/초`:"연결 중"}</span></div>
    <dl className="order-counters">{[["남은 재고",data?.stock],["접수된 참여",data?.accepted],["확정 주문",data?.confirmed],["처리 대기",data?.pending]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{number(value as number|undefined)}</dd></div>)}</dl>
    <div className="order-pulse-controls"><button type="button" className={running?"running":""} aria-pressed={running} disabled={!data||(!running&&(!valid||data.stock===0))} onClick={()=>{active.current=!active.current;setRunning(active.current);}}>{running?<Pause size={13} weight="fill"/>:<Play size={13} weight="fill"/>}{running?"주문 정지":"주문 시작"}</button><label htmlFor="order-rate" className="sr-only">초당 주문 목표 건수</label><input id="order-rate" type="number" min="1" max="100" value={rate} aria-invalid={!valid} disabled={running} onChange={e=>setRate(e.target.value)}/><span>건/초</span>{data&&data.sold_out>0&&<span className="order-rejected">품절 {data.sold_out.toLocaleString()}</span>}</div>
    {(!valid||sendError)&&<p role="status" className="order-pulse-error">{!valid?"1~100건으로 입력해 주세요.":sendError}</p>}
  </section>;
}
