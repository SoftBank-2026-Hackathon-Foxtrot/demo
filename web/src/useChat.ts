import { useEffect, useRef, useState } from "react";

export type ChatMessage = { id: string; user: string; text: string; at: number; source?: "human" | "bot" };
type Connection = "connecting" | "connected" | "reconnecting";

export function useChat(sid: string, onSessionLost: () => void) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [humanMessages, setHumanMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<Connection>("connecting");
  const [error, setError] = useState("");
  const [bot, setBot] = useState({ rate: 0, error: "" });
  const [pending, setPending] = useState<{ id: string; text: string } | null>(null);
  const [info, setInfo] = useState({ server: "", environment: "", connection: "", reconnects: 0, received: 0 });
  const [measuredSince, setMeasuredSince] = useState<number | null>(null);
  const liveIds = useRef(new Set<string>());
  const socket = useRef<WebSocket | null>(null);
  const ackTimer = useRef<ReturnType<typeof setTimeout>>();
  const lost = useRef(onSessionLost);
  lost.current = onSessionLost;

  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout>;
    let watchdog: ReturnType<typeof setInterval>;
    let attempt = 0;
    let lastEvent = Date.now();
    const seen = new Set<string>();
    function merge(incoming: ChatMessage[]) {
      setMessages((previous) => {
        const items = new Map(previous.map((m) => [m.id, m]));
        for (const message of incoming) items.set(message.id, message);
        return [...items.values()].sort((a, b) => a.at - b.at || a.id.localeCompare(b.id)).slice(-200);
      });
    }
    function connect() {
      if (stopped) return;
      const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/live/chat`);
      socket.current = ws;
      lastEvent = Date.now();
      ws.onopen = () => ws.send(JSON.stringify({ sid }));
      ws.onmessage = (event) => {
        if (stopped) return;
        lastEvent = Date.now();
        const data = JSON.parse(event.data);
        if (data.type === "history") merge(data.messages);
        if (data.type === "bot_state") setBot({ rate: data.rate, error: data.error || "" });
        if (data.type === "ready") {
          attempt = 0;
          setStatus("connected");
          setMeasuredSince((since) => since ?? data.measurement_since_ms ?? null);
          setInfo((i) => ({ ...i, server: `${data.served_by} · ${data.pid}`, environment: data.served_by, connection: data.connection_id }));
        }
        if (data.type === "message") {
          liveIds.current.add(data.message.id);
          if (liveIds.current.size > 20000) liveIds.current.delete(liveIds.current.values().next().value!);
          merge([data.message]);
          if (!seen.has(data.message.id)) {
            if (data.message.source === "human") setHumanMessages(previous => [...previous, data.message].slice(-40));
            seen.add(data.message.id);
            if (seen.size > 1000) seen.delete(seen.values().next().value!);
            setInfo((i) => ({ ...i, received: i.received + 1 }));
          }
        }
        if (data.type === "ack") {
          setPending((p) => p?.id === data.id ? null : p);
          clearTimeout(ackTimer.current);
          setError("");
        }
        if (data.type === "error") {
          setError(data.message);
          clearTimeout(ackTimer.current);
        }
      };
      ws.onclose = (event) => {
        if (stopped) return;
        setBot({ rate: 0, error: "" });
        if (event.code === 4401) { lost.current(); return; }
        setStatus("reconnecting");
        setInfo((i) => ({ ...i, reconnects: i.reconnects + 1 }));
        retry = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 8000));
      };
    }
    connect();
    watchdog = setInterval(() => {
      if (Date.now() - lastEvent > 45000) socket.current?.close();
    }, 5000);
    return () => {
      stopped = true;
      clearTimeout(retry);
      clearInterval(watchdog);
      clearTimeout(ackTimer.current);
      socket.current?.close();
    };
  }, [sid]);

  function send(text: string, id: string = crypto.randomUUID()) {
    if (socket.current?.readyState !== WebSocket.OPEN || status !== "connected") {
      setError("채팅방에 다시 연결되면 보내 주세요.");
      return false;
    }
    setError("");
    setPending({ id, text });
    socket.current.send(JSON.stringify({ id, text }));
    clearTimeout(ackTimer.current);
    ackTimer.current = setTimeout(() => setError("아직 전달을 확인하지 못했어요. 다시 보내기를 눌러 주세요."), 12000);
    return true;
  }
  function editPending() {
    clearTimeout(ackTimer.current);
    setPending(null);
    setError("");
  }
  function setBotRate(rate: number) {
    if (socket.current?.readyState !== WebSocket.OPEN || status !== "connected") return;
    socket.current.send(JSON.stringify({ type: "bot", rate }));
  }
  return { messages, humanMessages, status, error, pending, info, send, editPending, bot, setBotRate, measuredSince, liveIds };
}
