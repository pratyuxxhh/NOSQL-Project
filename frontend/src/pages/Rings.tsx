import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { patch, post, type GraphData, type GraphNode } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { GraphView, NodeDetails } from "../components/GraphView";
import { Badge, Button, Card, ErrorBox, inputClass, Loading, money, PageHeader, pct, Table, Td, when } from "../components/ui";
import { useApi } from "../hooks/useApi";

type Ring = Record<string, unknown> & { ring_id: string; status: string; size: number };

const STATUSES = ["", "NEW", "UNDER_REVIEW", "CONFIRMED_FRAUD", "FALSE_POSITIVE"];

export function RingList() {
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [running, setRunning] = useState(false);
  const [algorithm, setAlgorithm] = useState("louvain");
  const [message, setMessage] = useState<string | null>(null);
  const { data, error, reload } = useApi<{ total: number; items: Ring[] }>(
    `/api/v1/rings?page=${page}&page_size=20${status ? `&status=${status}` : ""}`,
  );

  const detect = async () => {
    setRunning(true);
    try {
      const r = await post<Record<string, number>>(`/api/v1/rings/detect?algorithm=${algorithm}`);
      setMessage(`${r.rings} rings (${r.new_rings} new) from ${r.communities} communities in ${r.duration_ms} ms`);
      await reload();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Fraud rings"
        subtitle="Groups of accounts tied together by shared devices, cards, addresses and phones"
        actions={
          can("ANALYST") && (
            <div className="flex gap-2">
              <select className={inputClass} value={algorithm} onChange={(e) => setAlgorithm(e.target.value)}>
                <option value="louvain">Louvain</option>
                <option value="lpa">Label Propagation</option>
              </select>
              <Button onClick={detect} disabled={running}>{running ? "Detecting…" : "Run detection now"}</Button>
            </div>
          )
        }
      />
      {message && <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">{message}</p>}
      <ErrorBox error={error} />
      <Card
        actions={
          <select className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            {STATUSES.map((s) => <option key={s} value={s}>{s ? s.replaceAll("_", " ") : "All statuses"}</option>)}
          </select>
        }
        title={data ? `${data.total} rings` : "Rings"}
      >
        {!data ? <Loading /> : (
          <Table head={["Ring", "Status", "Size", "Density", "Avg risk", "Devices", "Cards", "Addresses", "Phones", "Known fraud", "Volume", "Detected"]}>
            {data.items.map((r) => (
              <tr key={r.ring_id}>
                <Td><Link className="font-mono text-blue-600 hover:underline dark:text-blue-400" to={`/rings/${r.ring_id}`}>{r.ring_id}</Link></Td>
                <Td><Badge value={r.status} /></Td>
                <Td className="tabular-nums">{r.size}</Td>
                <Td className="tabular-nums">{Number(r.density).toFixed(2)}</Td>
                <Td className="tabular-nums">{pct(r.avg_risk)}</Td>
                <Td className="tabular-nums">{String(r.shared_devices)}</Td>
                <Td className="tabular-nums">{String(r.shared_cards)}</Td>
                <Td className="tabular-nums">{String(r.shared_addresses)}</Td>
                <Td className="tabular-nums">{String(r.shared_phones)}</Td>
                <Td className="tabular-nums">{String(r.flagged_members ?? 0)}</Td>
                <Td className="tabular-nums">{money(r.total_volume)}</Td>
                <Td className="whitespace-nowrap">{when(r.detected_at)}</Td>
              </tr>
            ))}
          </Table>
        )}
        {data && data.total > 20 && (
          <div className="mt-3 flex gap-2">
            <Button variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <Button variant="secondary" disabled={page * 20 >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        )}
      </Card>
    </>
  );
}

interface RingDetail {
  ring: Ring;
  members: Record<string, unknown>[];
  graph: GraphData;
}

const NEXT: Record<string, string[]> = {
  NEW: ["UNDER_REVIEW", "CONFIRMED_FRAUD", "FALSE_POSITIVE"],
  UNDER_REVIEW: ["CONFIRMED_FRAUD", "FALSE_POSITIVE"],
};

export function RingDetailPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data, error, reload } = useApi<RingDetail>(`/api/v1/rings/${id}`);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [note, setNote] = useState("");
  const [result, setResult] = useState<string | null>(null);

  const move = async (status: string) => {
    if (status === "CONFIRMED_FRAUD" && !confirm("Confirm this ring as fraud? All members will be flagged and their risk will propagate.")) return;
    try {
      const r = await patch<{ flagged?: string[]; propagation?: { affected: number; pre_emptive: unknown[] } }>(
        `/api/v1/rings/${id}/status`, { status, note });
      setResult(
        r.propagation
          ? `Flagged ${r.flagged?.length} accounts. Risk reached ${r.propagation.affected} accounts; ${r.propagation.pre_emptive.length} pre-emptive detections.`
          : `Status changed to ${status.replaceAll("_", " ")}.`,
      );
      await reload();
    } catch (e) {
      setResult(e instanceof Error ? e.message : String(e));
    }
  };

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const r = data.ring;

  return (
    <>
      <PageHeader
        title={`Ring ${r.ring_id}`}
        subtitle={`${r.size} accounts · algorithm ${String(r.algorithm)} · density ${Number(r.density).toFixed(2)} · ${Math.round(Number(r.new_account_ratio ?? 0) * 100)}% new accounts · hub ${String(r.hub_account ?? "–")}`}
        actions={<Badge value={r.status} />}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Ring graph" className="lg:col-span-2">
          <GraphView data={data.graph} onSelect={setSelected} />
        </Card>
        <div className="space-y-4">
          {can("ANALYST") && NEXT[r.status] && (
            <Card title="Review">
              <textarea className={`${inputClass} mb-2 w-full`} rows={2} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="flex flex-wrap gap-2">
                {NEXT[r.status].map((s) => (
                  <Button key={s} variant={s === "CONFIRMED_FRAUD" ? "danger" : "secondary"} onClick={() => move(s)}>
                    {s === "CONFIRMED_FRAUD" ? "Confirm fraud" : s === "FALSE_POSITIVE" ? "False positive" : "Start review"}
                  </Button>
                ))}
              </div>
            </Card>
          )}
          {result && <p className="text-sm">{result}</p>}
          <Card title="Selected node"><NodeDetails node={selected} /></Card>
        </div>
      </div>
      <Card title="Members" className="mt-4">
        <Table head={["Account", "Hub score", "Combined risk", "Propagated", "Flagged", "Opened"]}>
          {data.members.map((m) => (
            <tr key={String(m.id)}>
              <Td className="font-mono text-xs">{String(m.id)}</Td>
              <Td className="tabular-nums">{Number(m.hub_score ?? 0).toFixed(3)}</Td>
              <Td className="tabular-nums">{pct(m.combined_risk)}</Td>
              <Td className="tabular-nums">{pct(m.propagated_risk)}</Td>
              <Td>{m.is_flagged ? <Badge value="HIGH" /> : ""}</Td>
              <Td>{when(m.opened_at)}</Td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
