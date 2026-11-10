import { useCallback, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, ErrorBox, Kpi, Loading, money, PageHeader, Table, Td } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useLive, type LiveEvent } from "../hooks/useLive";

interface Tx {
  id: string;
  account_id: string;
  amount: number;
  channel: string;
  location: string;
  timestamp: string;
  rule_score: number;
  final_score: number;
  decision?: string;
  linked_to_fraud?: boolean;
}
interface OverviewData {
  kpis: Record<string, number>;
  alerts_by_day: Record<string, string | number>[];
  risk_distribution: { range: string; accounts: number }[];
  recent_transactions: Tx[];
  metrics: Record<string, unknown>;
}

const ALERT_COLORS: Record<string, string> = {
  HIGH_RULE_SCORE: "#d97706",
  RING_DETECTED: "#dc2626",
  PROPAGATED_RISK: "#9333ea",
  LINKED_TO_FRAUD: "#2563eb",
};

export default function Overview() {
  const { data, error, reload, setData } = useApi<OverviewData>("/api/v1/stats/overview");
  const [liveCount, setLiveCount] = useState(0);

  const onEvent = useCallback(
    (e: LiveEvent) => {
      if (e.event === "transaction") {
        setLiveCount((n) => n + 1);
        setData((d) => (d ? { ...d, recent_transactions: [e.data as unknown as Tx, ...d.recent_transactions].slice(0, 25) } : d));
      }
      if (e.event === "alert" || e.event === "ring") void reload();
    },
    [reload, setData],
  );
  const connected = useLive(onEvent);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const k = data.kpis;
  const m = data.metrics;

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle="Live state of the transaction graph"
        actions={
          <span className={`text-sm ${connected ? "text-green-600" : "text-slate-500"}`}>
            {connected ? `● Live (${liveCount} new transactions)` : "○ Live feed disconnected"}
          </span>
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Transactions (24h)" value={k.tx_24h.toLocaleString()} hint={`${k.tx_total.toLocaleString()} total`} />
        <Kpi label="Open alerts" value={k.open_alerts} tone={k.open_alerts ? "warning" : "default"} />
        <Kpi label="Active rings" value={k.active_rings} tone={k.active_rings ? "danger" : "default"} />
        <Kpi label="Accounts at risk" value={k.accounts_at_risk} hint="combined risk ≥ 0.5" />
        <Kpi label="Pre-emptive detections" value={k.pre_emptive} hint="no rule fired" tone="warning" />
        <Kpi label="Known fraud" value={k.flagged} hint="flagged accounts" />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Alerts over time (14 days)">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={data.alerts_by_day}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="day" fontSize={11} />
              <YAxis allowDecimals={false} fontSize={11} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {Object.entries(ALERT_COLORS).map(([type, color]) => (
                <Bar key={type} dataKey={type} stackId="a" fill={color} name={type.replaceAll("_", " ")} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Account risk distribution (combined risk > 0)">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={data.risk_distribution}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="range" fontSize={11} />
              <YAxis allowDecimals={false} fontSize={11} />
              <Tooltip />
              <Bar dataKey="accounts" fill="#2563eb" />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Live transaction feed" className="lg:col-span-2">
          <Table head={["Time", "Transaction", "Account", "Amount", "Channel", "Rule", "Final", "Decision"]}>
            {data.recent_transactions.map((t) => (
              <tr key={t.id} className={t.linked_to_fraud ? "bg-red-50 dark:bg-red-950/40" : ""}>
                <Td className="whitespace-nowrap">{new Date(t.timestamp).toLocaleTimeString()}</Td>
                <Td className="font-mono text-xs">{t.id}</Td>
                <Td className="font-mono text-xs">{t.account_id}</Td>
                <Td className="tabular-nums">{money(t.amount)}</Td>
                <Td>{t.channel}</Td>
                <Td className="tabular-nums">{t.rule_score ?? "–"}</Td>
                <Td className="tabular-nums">{typeof t.final_score === "number" ? t.final_score.toFixed(0) : "–"}</Td>
                <Td><Badge value={t.decision} /></Td>
              </tr>
            ))}
          </Table>
        </Card>
        <Card title="System metrics">
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-slate-500">Ingested (session)</dt><dd className="tabular-nums">{String(m.ingested_total)}</dd>
            <dt className="text-slate-500">Rate (last min)</dt><dd className="tabular-nums">{String(m.ingest_rate_per_min)}/min</dd>
            <dt className="text-slate-500">Latency p50</dt><dd className="tabular-nums">{m.latency_ms_p50 == null ? "–" : `${m.latency_ms_p50} ms`}</dd>
            <dt className="text-slate-500">Latency p95</dt><dd className="tabular-nums">{m.latency_ms_p95 == null ? "–" : `${m.latency_ms_p95} ms`}</dd>
            <dt className="text-slate-500">Queue depth</dt><dd className="tabular-nums">{String(m.queue_depth)}</dd>
            <dt className="text-slate-500">Last detection</dt>
            <dd className="tabular-nums">
              {m.last_detection ? `${(m.last_detection as Record<string, number>).duration_ms} ms` : "–"}
            </dd>
          </dl>
        </Card>
      </div>
    </>
  );
}
