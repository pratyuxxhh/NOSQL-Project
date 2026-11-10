import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, ErrorBox, Kpi, Loading, PageHeader, Table, Td } from "../components/ui";
import { useApi } from "../hooks/useApi";

interface Group {
  count: number;
  sample: string[];
  actually_fraud?: number;
}
interface Metrics {
  precision: number;
  recall: number;
  f1: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
}
interface ComparisonData {
  rules_only: Group;
  graph_only: Group;
  both: Group;
  evaluation: {
    truth: { fraud_accounts: number; known_flagged_excluded: number };
    account_level: Record<string, Metrics>;
    ring_level: { found: number; total: number; by_type: Record<string, string> };
  } | null;
}

const NAMES: Record<string, string> = {
  rules_only: "Rules only (baseline)",
  graph_detection: "Graph ring detection",
  graph_plus_propagation: "Graph + propagation",
};

export default function Comparison() {
  const { data, error } = useApi<ComparisonData>("/api/v1/stats/comparison");
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const ev = data.evaluation;
  const chart = ev
    ? Object.entries(ev.account_level).map(([k, m]) => ({ name: NAMES[k] ?? k, precision: m.precision, recall: m.recall, f1: m.f1 }))
    : [];

  return (
    <>
      <PageHeader title="Rules vs Graph" subtitle="Which suspicious accounts does each approach catch? (already-flagged accounts excluded)" />
      <div className="grid gap-3 md:grid-cols-3">
        <Group title="Caught by rules only" group={data.rules_only} tone="default" />
        <Group title="Caught by graph only" group={data.graph_only} tone="danger" />
        <Group title="Caught by both" group={data.both} tone="warning" />
      </div>
      {ev ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Card title={`Detection quality vs ground truth (${ev.truth.fraud_accounts} hidden fraud accounts)`}>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                <XAxis dataKey="name" fontSize={11} />
                <YAxis domain={[0, 1]} fontSize={11} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="precision" fill="#2563eb" />
                <Bar dataKey="recall" fill="#d97706" />
                <Bar dataKey="f1" fill="#16a34a" />
              </BarChart>
            </ResponsiveContainer>
          </Card>
          <Card title="Numbers">
            <Table head={["Approach", "Precision", "Recall", "F1", "TP", "FP", "FN"]}>
              {Object.entries(ev.account_level).map(([k, m]) => (
                <tr key={k}>
                  <Td>{NAMES[k] ?? k}</Td>
                  <Td className="tabular-nums">{m.precision.toFixed(3)}</Td>
                  <Td className="tabular-nums">{m.recall.toFixed(3)}</Td>
                  <Td className="tabular-nums font-semibold">{m.f1.toFixed(3)}</Td>
                  <Td className="tabular-nums">{m.true_positives}</Td>
                  <Td className="tabular-nums">{m.false_positives}</Td>
                  <Td className="tabular-nums">{m.false_negatives}</Td>
                </tr>
              ))}
            </Table>
            <p className="mt-3 text-sm">
              Planted rings found: <b>{ev.ring_level.found}/{ev.ring_level.total}</b>{" "}
              <span className="text-slate-500">({Object.entries(ev.ring_level.by_type).map(([t, v]) => `${t.replaceAll("_", " ")} ${v}`).join(", ")})</span>
            </p>
          </Card>
        </div>
      ) : (
        <Card className="mt-4"><p className="text-sm">No evaluation yet. Run <code>make evaluate</code> (or <code>docker compose exec backend python -m app.evaluation</code>).</p></Card>
      )}
    </>
  );
}

function Group({ title, group, tone }: { title: string; group: Group; tone: "default" | "danger" | "warning" }) {
  return (
    <div>
      <Kpi label={title} value={group.count} tone={tone} hint={group.actually_fraud !== undefined ? `${group.actually_fraud} of them are planted fraud` : undefined} />
      <p className="mt-1 truncate font-mono text-xs text-slate-500" title={group.sample.join(", ")}>{group.sample.slice(0, 8).join(", ")}</p>
    </div>
  );
}
