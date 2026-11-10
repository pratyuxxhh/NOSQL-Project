import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, post, type GraphData } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { GraphView } from "../components/GraphView";
import { Badge, Button, Card, ErrorBox, inputClass, PageHeader, pct, Table, Td } from "../components/ui";
import { useApi } from "../hooks/useApi";

interface Affected {
  id: string;
  propagated_risk: number;
  combined_risk: number;
  pre_emptive: boolean;
  hops: number;
  explanation: string[];
}
interface Spread {
  source: Record<string, unknown>;
  affected: Affected[];
  graph: GraphData;
}

export default function RiskPropagation() {
  const { can } = useAuth();
  const flagged = useApi<Record<string, unknown>[]>("/api/v1/risk/accounts?min_risk=1&limit=200");
  const preEmptive = useApi<Record<string, unknown>[]>("/api/v1/risk/accounts?min_risk=0&pre_emptive=true&limit=50");
  const [account, setAccount] = useState("");
  const [spread, setSpread] = useState<Spread | null>(null);
  const [hop, setHop] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = async (id: string) => {
    setError(null);
    setAccount(id);
    try {
      setSpread(await api<Spread>(`/api/v1/risk/spread/${encodeURIComponent(id)}`));
      setHop(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // Animate: reveal the affected accounts one hop at a time.
  useEffect(() => {
    if (!spread) return;
    const maxHop = Math.max(0, ...spread.affected.map((a) => a.hops));
    if (hop >= maxHop) return;
    const timer = setTimeout(() => setHop((h) => h + 1), 1200);
    return () => clearTimeout(timer);
  }, [spread, hop]);

  const highlight = useMemo(() => {
    if (!spread) return new Set<string>();
    const ids = new Set(spread.affected.filter((a) => a.hops <= hop).map((a) => a.id));
    ids.add(String(spread.source.id));
    return new Set(spread.graph.nodes.filter((n) => ids.has(n.key)).map((n) => n.id));
  }, [spread, hop]);

  const flag = async (e: FormEvent) => {
    e.preventDefault();
    if (!confirm(`Flag ${account} as fraud and propagate its risk?`)) return;
    try {
      const r = await post<{ affected: number; pre_emptive: unknown[] }>(`/api/v1/risk/propagate/${encodeURIComponent(account)}`, { reason: "Flagged from dashboard" });
      setMessage(`Risk reached ${r.affected} accounts; ${r.pre_emptive.length} pre-emptive detections.`);
      await load(account);
      void flagged.reload();
      void preEmptive.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <>
      <PageHeader title="Risk Propagation" subtitle="Risk spreads from flagged accounts: weighted by link type, halved with every hop, combined with noisy-OR" />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Flagged accounts (sources)">
          <div className="flex max-h-48 flex-wrap gap-1.5 overflow-y-auto">
            {(flagged.data ?? []).map((a) => (
              <button key={String(a.id)} onClick={() => load(String(a.id))} className={`rounded px-2 py-0.5 font-mono text-xs ${account === a.id ? "bg-red-600 text-white" : "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"}`}>
                {String(a.id)}
              </button>
            ))}
          </div>
          {can("ANALYST") && (
            <form onSubmit={flag} className="mt-4 flex gap-2">
              <input className={`${inputClass} flex-1`} value={account} onChange={(e) => setAccount(e.target.value)} placeholder="Account to flag" />
              <Button variant="danger" type="submit" disabled={!account}>Flag & propagate</Button>
            </form>
          )}
          {message && <p className="mt-2 text-sm">{message}</p>}
        </Card>
        <Card title="Pre-emptive detections" className="lg:col-span-2">
          <p className="mb-2 text-xs text-slate-500">Accounts surfaced by propagated risk although no rule ever fired on them.</p>
          <Table head={["Account", "Propagated", "Why"]}>
            {(preEmptive.data ?? []).slice(0, 8).map((a) => (
              <tr key={String(a.id)}>
                <Td className="font-mono text-xs">{String(a.id)}</Td>
                <Td className="tabular-nums">{pct(a.propagated_risk)}</Td>
                <Td className="font-mono text-xs">{((a.risk_explanation as string[]) ?? [])[0]}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
      <ErrorBox error={error} />
      {spread && (
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <Card title={`Spread from ${String(spread.source.id)} — hop ${hop}`} className="lg:col-span-2" actions={<Button variant="secondary" onClick={() => setHop(0)}>Replay</Button>}>
            <GraphView data={spread.graph} highlight={highlight} layout="concentric" />
          </Card>
          <Card title={`${spread.affected.length} accounts affected`}>
            <div className="max-h-[560px] overflow-y-auto">
              <Table head={["Account", "Hops", "Risk", ""]}>
                {spread.affected.map((a) => (
                  <tr key={a.id} className={a.hops <= hop ? "" : "opacity-40"}>
                    <Td className="font-mono text-xs" >
                      <div>{a.id}</div>
                      <div className="text-[10px] text-slate-500">{a.explanation[0]}</div>
                    </Td>
                    <Td className="tabular-nums">{a.hops}</Td>
                    <Td className="tabular-nums">{pct(a.propagated_risk)}</Td>
                    <Td>{a.pre_emptive && <Badge value="REVIEW" />}</Td>
                  </tr>
                ))}
              </Table>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}
