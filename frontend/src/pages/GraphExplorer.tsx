import { useEffect, useState, type FormEvent } from "react";
import { api, type GraphData, type GraphNode } from "../api/client";
import { GraphView, NodeDetails } from "../components/GraphView";
import { Button, Card, ErrorBox, inputClass, PageHeader } from "../components/ui";

const REL_TYPES = [
  "SHARED_DEVICE", "SHARED_CARD", "SHARED_ADDRESS", "SHARED_PHONE", "TRANSACTED_WITH",
  "OWNS", "USES_DEVICE", "USES_CARD", "LIVES_AT", "HAS_PHONE", "MEMBER_OF", "FLAGGED_BY",
];
const DEFAULT_TYPES = ["SHARED_DEVICE", "SHARED_CARD", "SHARED_ADDRESS", "SHARED_PHONE", "OWNS", "USES_DEVICE", "USES_CARD", "LIVES_AT", "HAS_PHONE"];

function merge(a: GraphData, b: GraphData): GraphData {
  const nodes = new Map(a.nodes.map((n) => [n.id, n]));
  b.nodes.forEach((n) => nodes.set(n.id, n));
  const edges = new Map(a.edges.map((e) => [e.id, e]));
  b.edges.forEach((e) => edges.set(e.id, e));
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

export default function GraphExplorer() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GraphNode[]>([]);
  const [depth, setDepth] = useState(1);
  const [types, setTypes] = useState<string[]>(DEFAULT_TYPES);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }
    const timer = setTimeout(() => {
      api<GraphNode[]>(`/api/v1/graph/search?q=${encodeURIComponent(query.trim())}`).then(setResults).catch(() => setResults([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  const expand = async (node: Pick<GraphNode, "label" | "key">, append: boolean) => {
    setError(null);
    try {
      const params = new URLSearchParams({ label: node.label, depth: String(depth) });
      types.forEach((t) => params.append("types", t));
      const data = await api<GraphData & { truncated: boolean }>(`/api/v1/graph/neighbourhood/${encodeURIComponent(node.key)}?${params}`);
      setTruncated(data.truncated);
      setGraph((g) => (append && g ? merge(g, data) : data));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (results[0]) void expand(results[0], false);
  };

  return (
    <>
      <PageHeader title="Graph Explorer" subtitle="Search any account, device, card (last 4), address, merchant or person; expand neighbours hop by hop" />
      <Card>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            Search
            <input className={`${inputClass} mt-1 block w-64`} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="A006891, D000123, 4321, name…" />
          </label>
          <label className="text-sm">
            Depth
            <select className={`${inputClass} mt-1 block`} value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
              {[1, 2, 3, 4, 5, 6].map((d) => <option key={d}>{d}</option>)}
            </select>
          </label>
          <Button type="submit" disabled={!results.length}>Explore</Button>
          {graph && <Button type="button" variant="secondary" onClick={() => { setGraph(null); setSelected(null); }}>Clear</Button>}
        </form>
        {results.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {results.map((r) => (
              <button key={r.id} onClick={() => expand(r, false)} className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">
                <span className="text-slate-500">{r.label}</span> {r.caption}
              </button>
            ))}
          </div>
        )}
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-slate-600 dark:text-slate-400">Relationship types ({types.length})</summary>
          <div className="mt-2 flex flex-wrap gap-3">
            {REL_TYPES.map((t) => (
              <label key={t} className="flex items-center gap-1 text-xs">
                <input type="checkbox" checked={types.includes(t)} onChange={(e) => setTypes(e.target.checked ? [...types, t] : types.filter((x) => x !== t))} />
                {t}
              </label>
            ))}
          </div>
        </details>
      </Card>
      <ErrorBox error={error} />
      {graph && (
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <Card title={`${graph.nodes.length} nodes, ${graph.edges.length} relationships${truncated ? " (limit reached)" : ""}`} className="lg:col-span-2">
            <GraphView data={graph} onSelect={setSelected} />
          </Card>
          <Card title="Selected node" actions={selected && <Button variant="secondary" onClick={() => expand(selected, true)}>Expand +{depth}</Button>}>
            <NodeDetails node={selected} />
          </Card>
        </div>
      )}
    </>
  );
}
