import { useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import type { ChatMessage } from "./useChat";

type Entry = { message: ChatMessage; receivedAt: number };
const LIFETIME = 12000;
const MAX_VISIBLE = 9;

export function FloatingChat({ messages, liveIds }: { messages: ChatMessage[]; liveIds: Set<string> }) {
  const seen = useRef(new Set<string>());
  const [entries, setEntries] = useState<Entry[]>([]);
  const [now, setNow] = useState(Date.now);
  const reducedMotion = useReducedMotion();
  useEffect(() => {
    const receivedAt = Date.now();
    const incoming = messages.filter(message => liveIds.has(message.id) && !seen.current.has(message.id));
    if (!incoming.length) return;
    for (const message of incoming) seen.current.add(message.id);
    if (seen.current.size > 2000) seen.current = new Set(messages.map(message => message.id));
    setEntries(previous => [...previous.filter(entry=>receivedAt-entry.receivedAt<LIFETIME), ...incoming.map(message=>({message,receivedAt}))].slice(-MAX_VISIBLE));
    setNow(receivedAt);
  }, [messages, liveIds]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, []);
  const visible = entries.filter(entry => now - entry.receivedAt < LIFETIME);
  return <div className="floating-chat" role="log" aria-label="방송 화면 실시간 채팅" aria-live="off">
    {visible.map(({message,receivedAt},index) => {
      const age = Math.max(0, now-receivedAt)/LIFETIME;
      const depth = (visible.length-1-index)/MAX_VISIBLE;
      return <motion.div key={message.id} layout={reducedMotion?false:"position"} initial={reducedMotion?false:{opacity:0,y:16}} animate={{opacity:1,y:0}} transition={{duration:reducedMotion?0:.28}} className="floating-chat-entry">
        <div className="floating-chat-bubble" style={{opacity:Math.max(0,1-age*.95-depth*.35), filter:reducedMotion?"none":`blur(${(age*.75+depth)*2}px)`, transform:reducedMotion?undefined:`translateY(${-age*60}px)`}}><strong>{message.user}</strong><span>{message.text}</span></div>
      </motion.div>;
    })}
  </div>;
}
