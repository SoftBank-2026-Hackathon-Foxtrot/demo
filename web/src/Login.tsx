import { useId, useState, type FormEvent } from "react";
import { login } from "./api";
import { Announcement, Header } from "./TopBar";

export function Login({ onDone }: { onDone: (sid: string, name: string) => void }) {
  const id = useId();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("닉네임을 입력해 주세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      onDone(await login(trimmed), trimmed);
    } catch {
      setError("지금은 입장할 수 없어요. 잠시 뒤 다시 시도해 주세요.");
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[100dvh]">
      <Announcement />
      <Header name={null} count={0} />
      <main className="login-layout">
        <div className="login-visual"><img src="/live-studio.png" alt="치이카와와 친구들이 기다리는 작은 공구방" /><p>좋아하는 마음이 모이면, 더 귀여워!</p></div>
        <div className="login-form">
          <span className="eyebrow"><span className="live-dot" /> CHIIKAWA LIVE</span>
          <h1>어서 와요,<br />우리들의 작은 공구방</h1>
          <p>치이카와 친구들과 굿즈도 구경하고, 수다도 떨어요.<br />닉네임 하나면 준비 끝!</p>
          <form onSubmit={submit} noValidate className="mt-6 flex flex-col gap-2">
            <label htmlFor={id} className="text-sm font-semibold">닉네임</label>
            <input
              id={id}
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={20}
              autoComplete="nickname"
              enterKeyHint="go"
              aria-invalid={!!error}
              aria-describedby={error ? `${id}-error` : undefined}
              className="h-13 rounded-xl border-2 border-ink bg-surface px-4 text-base text-ink focus:border-accent"
            />
            {error && <p id={`${id}-error`} role="alert" className="text-sm font-semibold text-accent">{error}</p>}
            <button disabled={busy} className="mt-3 h-13 rounded-full border-2 border-ink bg-accent font-bold text-on-accent transition active:scale-[0.98] disabled:opacity-60">
              {busy ? "입장하는 중" : "라이브 공구방 입장하기 →"}
            </button>
          </form>
          <p className="login-note">해커톤 시연을 위한 비공식 데모예요.<br />실제 결제와 배송은 이루어지지 않아요.</p>
        </div>
      </main>
    </div>
  );
}
