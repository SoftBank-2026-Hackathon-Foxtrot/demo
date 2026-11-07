import { useEffect, useState, type MutableRefObject } from "react";
import { readLiveMetrics, saveBaseline, SessionLost, type Baseline, type LiveMetrics } from "./api";

export function environmentName(value: string) {
  const name = value.toLowerCase();
  if (/(^|[-_ ])aws($|[-_ ])/.test(name)) return "AWS";
  if (/(^|[-_ ])gcp($|[-_ ])/.test(name)) return "GCP";
  if (/onprem|on-prem|on_prem/.test(name)) return "온프레미스";
  if (name === "local") return "로컬";
  return value ? `미확인 (${value})` : "확인 중";
}

function readBaseline(key: string): Baseline | null {
  try { return JSON.parse(sessionStorage.getItem(key) || "null"); } catch { return null; }
}

function percentage(found: number, expected: number) {
  return expected ? found / expected * 100 : null;
}

export function MigrationStatus({ sid, since, liveIds, chatEnvironment, connected, onSessionLost }: {
  sid: string; since: number | null; liveIds: MutableRefObject<Set<string>>; chatEnvironment: string;
  connected: boolean; onSessionLost: () => void;
}) {
  const storageKey = `migration-baseline:${sid}`;
  const [baseline, setBaseline] = useState<Baseline | null>(() => readBaseline(storageKey));
  const [metrics, setMetrics] = useState<LiveMetrics | null>(null);
  const [delivered, setDelivered] = useState(0);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    if (since === null) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    setMetrics(null);
    async function poll() {
      try {
        const result = await readLiveMetrics(sid, since!, baseline?.ids ?? null);
        if (stopped) return;
        setDelivered(result.chat_ids.filter((id) => liveIds.current.has(id)).length);
        setMetrics(result);
        setError("");
      } catch (e) {
        if (stopped) return;
        if (e instanceof SessionLost) { onSessionLost(); return; }
        setError("측정값을 갱신하지 못했어요. 다시 확인하고 있어요.");
      }
      if (!stopped) timer = setTimeout(poll, 3000);
    }
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [sid, since, baseline, liveIds, onSessionLost]);

  async function capture() {
    setSaving(true);
    setSaveError("");
    try {
      const result = await saveBaseline(sid);
      setBaseline(result);
      try { sessionStorage.setItem(storageKey, JSON.stringify(result)); }
      catch { setSaveError("브라우저 저장 공간을 사용할 수 없어 새로고침하면 기준이 사라져요."); }
    } catch (e) {
      if (e instanceof SessionLost) onSessionLost();
      else setSaveError("기준 데이터를 저장하지 못했어요. 다시 시도해 주세요.");
    } finally { setSaving(false); }
  }

  const fresh = metrics !== null && !error;
  const samples = metrics?.chat_ids.length ?? 0;
  const chatPercent = fresh ? percentage(delivered, samples) : null;
  const checks = Object.values(metrics?.retention ?? {});
  const expected = checks.reduce((sum, check) => sum + check.expected, 0);
  const retained = checks.reduce((sum, check) => sum + check.retained, 0);
  const dataPercent = fresh ? percentage(retained, expected) : null;

  return <section className="migration-status compact-monitor" aria-label="이전 상태 모니터"><details className="monitor-details"><summary><span className="monitor-label">이전 상태</span><span>채팅 <strong>{chatPercent===null?(error?"갱신 실패":"측정 대기"):chatPercent.toFixed(1)+"%"}</strong></span><span>데이터 <strong>{dataPercent===null?(error?"갱신 실패":!baseline?"기준 미저장":"측정 대기"):dataPercent.toFixed(1)+"%"}</strong></span><span className="monitor-where" title={"HTTP "+environmentName(metrics?.served_by ?? "")+" · 채팅 "+environmentName(chatEnvironment)}>HTTP {environmentName(metrics?.served_by??"")} · 채팅 {environmentName(chatEnvironment)}{!connected&&" · 재연결 중"}</span></summary><div className="monitor-expanded">
    <div className="migration-status-heading"><h2>이전 상태 <span className="eyebrow">LIVE MONITOR</span></h2><div className="environment-badges"><span>HTTP <strong>{environmentName(metrics?.served_by ?? "")}</strong></span><span className={connected ? "" : "disconnected"}>채팅 <strong>{environmentName(chatEnvironment)}</strong>{!connected && " · 재연결 중"}</span></div></div>
    <div className="migration-measures">
      <Metric label="채팅 실시간 수신율" percent={chatPercent} empty={error ? "갱신 실패" : "측정 대기"} detail={`${delivered.toLocaleString()} / ${samples.toLocaleString()}건 수신`} />
      <Metric label="기준 데이터 유지율" percent={dataPercent} empty={error ? "갱신 실패" : !baseline ? "기준 저장 필요" : !metrics ? "측정 중" : "검사할 데이터 없음"} detail={baseline ? `${retained.toLocaleString()} / ${expected.toLocaleString()}건 조회 가능` : "이전 전에 기준을 저장해 주세요"} />
    </div>
    <div className="migration-status-footer"><span>{error || (metrics ? `${new Date(metrics.at).toLocaleTimeString("ko-KR", { hour12: false })} 확인 · 약 3초마다 갱신` : "채팅 연결 후 측정을 시작해요")}</span><button type="button" onClick={() => void capture()} disabled={saving || since === null}>{saving ? "기준 저장 중…" : baseline ? "기준 다시 저장" : "기준 저장"}</button></div>
    <details className="migration-method"><summary>측정 기준과 검사 범위</summary><p>환경은 서버의 SERVED_BY 설정을 표시해요. HTTP는 마지막 측정 요청, 채팅은 현재 WebSocket 연결을 처리한 서버예요. 앱 위치이며 DB·Redis의 위치를 뜻하지 않아요.</p><p>채팅은 이 화면에 연결된 뒤 저장된 최근 최대 1,000건 중 실시간으로 받은 메시지의 비율이에요. 전송 중인 최근 2초와 재접속 시 불러온 기록은 제외해요. 연결이 끊긴 동안 놓친 메시지도 집계하며, 새로고침하면 채팅 측정을 다시 시작해요.</p><p>데이터는 기준 시점의 채팅·주문·참여 요청·상품을 종류별 최대 500건씩 검사해요. ID가 남아 있는지 확인하는 표본 검사이며, 내용 일치나 전체 저장소의 무손실을 보증하는 수치는 아니에요. 기준은 이 브라우저 탭에 보관돼요.</p>{baseline && <p>기준 저장: {new Date(baseline.at).toLocaleString("ko-KR")}</p>}{metrics?.retention && <ul>{Object.entries(metrics.retention).map(([key, check]) => <li key={key}>{({ chat: "채팅", orders: "주문", requests: "참여 요청", goods: "상품" } as Record<string, string>)[key]}: {check.retained} / {check.expected}건</li>)}</ul>}</details>
  </div></details><button className="monitor-baseline" type="button" onClick={()=>void capture()} disabled={saving||since===null}>{saving?"저장 중…":baseline?"기준 갱신":"기준 저장"}</button>{saveError&&<p className="migration-error" role="alert">{saveError}</p>}</section>;
}

function Metric({ label, percent, empty, detail }: { label: string; percent: number | null; empty: string; detail: string }) {
  return <div className="migration-metric"><span>{label}</span><strong className={percent !== null && percent < 100 ? "degraded" : ""}>{percent === null ? empty : `${percent.toFixed(2)}%`}</strong><progress aria-label={label} max={100} value={percent ?? 0} /><small>{detail}</small></div>;
}
