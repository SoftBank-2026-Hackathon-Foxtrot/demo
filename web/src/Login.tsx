import { useId, useState, type FormEvent } from "react";
import { login } from "./api";
import { Announcement, DemoNotice, Header } from "./TopBar";

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
      <div className="h-3 bg-nav" />
      <DemoNotice />
      <main className="mx-auto w-full max-w-md px-4 pb-16">
        <div className="rounded-2xl border-2 border-ink bg-[var(--tile)] p-6">
          <h1 className="font-display text-3xl leading-tight text-accent">닉네임으로 입장하기</h1>
          <p className="mt-2 text-muted">닉네임만 정하면 바로 공구에 참여할 수 있어요.</p>
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
              {busy ? "입장하는 중" : "입장하기"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
