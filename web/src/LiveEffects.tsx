import { useEffect, useRef, useState, type ReactNode, type CSSProperties } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Star, X } from "@phosphor-icons/react";
import QRCode from "qrcode";
import type { ChatMessage } from "./useChat";
import "./live-effects.css";

export function LiveDialog({title,onClose,children}:{title:string;onClose:()=>void;children:ReactNode}) {
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const dialog=ref.current;dialog?.showModal();return()=>dialog?.close();},[]);
  return <dialog ref={ref} className="live-dialog" aria-label={title} onCancel={onClose} onClick={event=>{if(event.target===event.currentTarget)onClose();}}><div className="live-dialog-heading"><strong>{title}</strong><button type="button" onClick={onClose} aria-label="설정 닫기"><X size={19}/></button></div>{children}</dialog>;
}

export function JoinQr({productId}:{productId?:number}) {
  const [image,setImage]=useState("");
  const [expanded,setExpanded]=useState(false);
  const configured=import.meta.env.VITE_PUBLIC_JOIN_URL as string|undefined;
  let candidate: URL;
  try { const parsed=new URL(configured || "/",window.location.origin);candidate=["http:","https:"].includes(parsed.protocol)?parsed:new URL("/",window.location.origin); }
  catch { candidate=new URL("/",window.location.origin); }
  if(productId)candidate.searchParams.set("order_product",String(productId));
  const url=candidate.href;
  useEffect(()=>{let current=true;void QRCode.toDataURL(url,{width:384,margin:4,errorCorrectionLevel:"M",color:{dark:"#493b30",light:"#fffdf8"}}).then(value=>{if(current)setImage(value);}).catch(()=>setImage(""));return()=>{current=false;};},[url]);
  if(!image)return <a className="join-qr-fallback" href={url}>입장</a>;
  return <><button type="button" className="join-qr" aria-label="입장 QR 확대" onClick={()=>setExpanded(true)}><img src={image} width="128" height="128" alt="라이브 입장 QR"/></button>{expanded&&<LiveDialog title="라이브 입장" onClose={()=>setExpanded(false)}><img className="join-qr-large" src={image} width="256" height="256" alt="라이브 입장 QR"/><a className="join-qr-url" href={url}>{candidate.host}</a></LiveDialog>}</>;
}

export function HumanChatSpotlight({messages}:{messages:ChatMessage[]}) {
  const seen=useRef(new Set<string>());
  const [bursts,setBursts]=useState<{message:ChatMessage;x:number;y:number;at:number}[]>([]);
  const reduced=useReducedMotion();
  useEffect(()=>{
    const incoming=messages.filter(message=>message.source==="human"&&!seen.current.has(message.id));
    incoming.forEach(message=>seen.current.add(message.id));
    if(seen.current.size>2000)seen.current=new Set(messages.map(message=>message.id));
    if(!incoming.length)return;
    const at=Date.now();
    setBursts(previous=>{
      const next=previous.filter(item=>at-item.at<2600);
      for(const message of incoming){
        let x=18+Math.random()*64,y=5+Math.random()*48,best=-1;
        for(let attempt=0;attempt<8;attempt++){
          const cx=18+Math.random()*64,cy=5+Math.random()*48;
          const distance=next.length?Math.min(...next.map(item=>(item.x-cx)**2+(item.y-cy)**2)):1;
          if(distance>best){x=cx;y=cy;best=distance;}
        }
        next.push({message,x,y,at});
      }
      return next.slice(-10);
    });
  },[messages]);
  useEffect(()=>{const timer=setInterval(()=>setBursts(previous=>previous.filter(item=>Date.now()-item.at<2600)),200);return()=>clearInterval(timer);},[]);
  return <div className="human-bursts" aria-hidden="true">{bursts.map(({message,x,y})=><div key={message.id} className="human-burst-position" style={{left:`${x}%`,top:`min(${y}%, calc(100% - 76px))`}}><motion.div data-human-message={message.id} className="human-star-burst" initial={reduced?false:{opacity:0,scale:.65,y:12}} animate={reduced?{opacity:1}:{opacity:[0,1,1,0],scale:[.65,1.13,1,1],y:[12,0,-4,-20]}} transition={{duration:reduced?0:2.5,times:[0,.12,.75,1]}}><span className="human-star-shape"><Star size={33} weight="fill"/>{!reduced&&[[-24,-19],[23,-16],[-29,7],[26,13],[-10,-31],[12,-29]].map(([dx,dy],index)=><Star key={index} size={7+index%3} weight="fill" className="human-star-speck" style={{"--dx":`${dx}px`,"--dy":`${dy}px`,animationDelay:`${index*25}ms`} as CSSProperties}/>)}</span><strong>{message.user}</strong><span className="human-star-text" title={message.text}>{message.text}</span></motion.div></div>)}</div>;
}
