import { useId, useState, type FormEvent } from "react";
import { login } from "./api";
import { Header } from "./TopBar";

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
      <Header name={null} count={0} />
      <main className="login-layout">
        <div className="login-visual"><img src="/live-studio.png" alt="치이카와 공구방" /></div>
        <div className="login-form">
          <h1>로그인</h1>
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
          <p className="login-note">시연용 데모 · 실제 결제 및 배송 없음</p>
        </div>
      </main>
    </div>
  );
}
