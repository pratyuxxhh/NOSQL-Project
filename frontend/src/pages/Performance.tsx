import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, ErrorBox, Kpi, Loading, PageHeader, Table, Td } from "../components/ui";
import { useApi } from "../hooks/useApi";

interface Row {
  depth: number;
  neo4j_ms: number;
  postgres_ms: number;
  neo4j_server_ms: number;
  postgres_server_ms: number;
  avg_accounts_reached: number;
}
interface Benchmark {
  available: boolean;
  links?: number;
  start_accounts?: number;
  note?: string;
  workloads?: Record<string, Row[]>;
}

const TITLES: Record<string, string> = {
  shared_attributes: "Shared attributes only",
  full_network: "Shared attributes + money transfers",
};

export default function Performance() {
  const bench = useApi<Benchmark>("/api/v1/stats/benchmark");
  const metrics = useApi<Record<string, unknown>>("/api/v1/stats/metrics");
  const m = metrics.data;

  return (
    <>
      <PageHeader title="Performance" subtitle="Live pipeline metrics and the Neo4j vs PostgreSQL traversal benchmark" />
      {m && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Ingestion latency p50" value={m.latency_ms_p50 == null ? "–" : `${m.latency_ms_p50} ms`} hint="event → graph → score → alerts" />
          <Kpi label="Ingestion latency p95" value={m.latency_ms_p95 == null ? "–" : `${m.latency_ms_p95} ms`} hint="target < 1000 ms" />
          <Kpi label="Ingested this session" value={String(m.ingested_total)} />
          <Kpi label="Last ring detection" value={m.last_detection ? `${(m.last_detection as Record<string, number>).duration_ms} ms` : "–"} />
        </div>
      )}
      <ErrorBox error={bench.error} />
      {!bench.data ? <Loading /> : !bench.data.available ? (
        <Card className="mt-4"><p className="text-sm">No benchmark yet. Run <code>make benchmark</code>.</p></Card>
      ) : (
        <>
          <p className="mt-4 text-sm text-slate-600 dark:text-slate-400">
            {bench.data.links?.toLocaleString()} account links, {bench.data.start_accounts} start accounts, depths 1–6. {bench.data.note}
          </p>
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            {Object.entries(bench.data.workloads ?? {}).map(([name, rows]) => (
              <Card key={name} title={TITLES[name] ?? name}>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={rows}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="depth" fontSize={11} label={{ value: "depth (hops)", position: "insideBottom", offset: -2, fontSize: 11 }} />
                    <YAxis fontSize={11} unit=" ms" />
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line dataKey="neo4j_ms" name="Neo4j (client)" stroke="#2563eb" />
                    <Line dataKey="postgres_ms" name="PostgreSQL (client)" stroke="#d97706" />
                    <Line dataKey="neo4j_server_ms" name="Neo4j (server)" stroke="#2563eb" strokeDasharray="4 3" />
                    <Line dataKey="postgres_server_ms" name="PostgreSQL (server)" stroke="#d97706" strokeDasharray="4 3" />
                  </LineChart>
                </ResponsiveContainer>
                <Table head={["Depth", "Neo4j ms", "Postgres ms", "Neo4j srv", "Postgres srv", "Reached"]}>
                  {rows.map((r) => (
                    <tr key={r.depth}>
                      <Td>{r.depth}</Td>
                      <Td className="tabular-nums">{r.neo4j_ms}</Td>
                      <Td className="tabular-nums">{r.postgres_ms}</Td>
                      <Td className="tabular-nums">{r.neo4j_server_ms}</Td>
                      <Td className="tabular-nums">{r.postgres_server_ms}</Td>
                      <Td className="tabular-nums">{r.avg_accounts_reached}</Td>
                    </tr>
                  ))}
                </Table>
              </Card>
            ))}
          </div>
        </>
      )}
    </>
  );
}
