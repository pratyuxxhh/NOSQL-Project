import { useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type GraphData } from "../api/client";
import { GraphView } from "../components/GraphView";
import { Button, Card, ErrorBox, inputClass, PageHeader } from "../components/ui";

interface PathResult extends GraphData {
  found: boolean;
  hops?: number;
  paths: string[];
}

export default function PathFinder() {
  const [params] = useSearchParams();
  const [from, setFrom] = useState(params.get("from") ?? "");
  const [to, setTo] = useState(params.get("to") ?? "");
  const [all, setAll] = useState(false);
  const [result, setResult] = useState<PathResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const q = new URLSearchParams({ from: from.trim(), to: to.trim(), all: String(all) });
      setResult(await api<PathResult>(`/api/v1/graph/shortest-path?${q}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const highlight = useMemo(() => new Set(result ? [...result.nodes.map((n) => n.id), ...result.edges.map((e) => e.id)] : []), [result]);

  return (
    <>
      <PageHeader title="Path Finder" subtitle="How are two accounts connected? Shortest path through shared devices, cards, addresses, phones and transfers" />
      <Card>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <label className="text-sm">From account<input className={`${inputClass} mt-1 block`} value={from} onChange={(e) => setFrom(e.target.value)} placeholder="A006878" required /></label>
          <label className="text-sm">To account<input className={`${inputClass} mt-1 block`} value={to} onChange={(e) => setTo(e.target.value)} placeholder="A006880" required /></label>
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />All shortest paths</label>
          <Button type="submit" disabled={busy}>{busy ? "Searching…" : "Find path"}</Button>
        </form>
      </Card>
      <ErrorBox error={error} />
      {result && !result.found && <p className="mt-4 text-sm">No connection found within 10 hops (merchants excluded).</p>}
      {result?.found && (
        <div className="mt-4 space-y-4">
          <Card title={`Connected in ${result.hops} hops`}>
            <ol className="space-y-1 text-sm">
              {result.paths.map((p, i) => <li key={i} className="font-mono break-words">{p}</li>)}
            </ol>
          </Card>
          <Card title="Path graph">
            <GraphView data={result} highlight={highlight} layout="breadthfirst" height={380} />
          </Card>
        </div>
      )}
    </>
  );
}
