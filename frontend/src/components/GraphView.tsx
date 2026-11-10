import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useEffect, useRef } from "react";
import type { GraphData, GraphNode } from "../api/client";

export const NODE_COLORS: Record<string, string> = {
  Account: "#2563eb",
  User: "#64748b",
  Device: "#d97706",
  Card: "#ea580c",
  Address: "#0d9488",
  Phone: "#9333ea",
  Merchant: "#16a34a",
  Transaction: "#94a3b8",
  Ring: "#dc2626",
  FraudFlag: "#dc2626",
  Analyst: "#475569",
};

function risk(node: GraphNode): number {
  const p = node.props;
  return Number(p.combined_risk ?? p.propagated_risk ?? p.risk_score ?? 0) || 0;
}

interface Props {
  data: GraphData;
  height?: number;
  highlight?: Set<string>; // element ids to emphasise (e.g. a path)
  onSelect?: (node: GraphNode) => void;
  layout?: "cose" | "breadthfirst" | "concentric";
  root?: string;
}

/** Interactive graph: nodes coloured by type, accounts sized by risk, flagged
 * accounts outlined in red, edges labelled by relationship type. */
export function GraphView({ data, height = 520, highlight, onSelect, layout = "cose", root }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const select = useRef(onSelect);
  select.current = onSelect;

  useEffect(() => {
    if (!container.current) return;
    const dark = document.documentElement.classList.contains("dark");
    const elements: ElementDefinition[] = [
      ...data.nodes.map((n) => ({
        data: {
          id: n.id,
          label: n.caption,
          color: NODE_COLORS[n.label] ?? "#64748b",
          size: n.label === "Account" ? 22 + risk(n) * 30 : 18,
          flagged: n.props.is_flagged ? 1 : 0,
          preEmptive: n.props.pre_emptive ? 1 : 0,
        },
        classes: highlight?.has(n.id) ? "hl" : "",
      })),
      ...data.edges.map((e) => ({
        // Edge labels only while the graph is small enough to read them.
        data: { id: e.id, source: e.source, target: e.target, label: data.edges.length <= 40 ? e.type : "", shared: e.type.startsWith("SHARED") ? 1 : 0 },
        classes: highlight?.has(e.id) ? "hl" : "",
      })),
    ];
    cy.current?.destroy();
    cy.current = cytoscape({
      container: container.current,
      elements,
      wheelSensitivity: 0.3,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            width: "data(size)",
            height: "data(size)",
            label: "data(label)",
            "font-size": 9,
            color: dark ? "#e2e8f0" : "#0f172a",
            "text-valign": "bottom",
            "text-margin-y": 3,
            "text-max-width": "90px",
            "text-wrap": "ellipsis",
          },
        },
        { selector: "node[flagged = 1]", style: { "border-width": 4, "border-color": "#dc2626" } },
        { selector: "node[preEmptive = 1]", style: { "border-width": 4, "border-color": "#f59e0b", "border-style": "dashed" } },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": dark ? "#475569" : "#cbd5e1",
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": 7,
            color: dark ? "#94a3b8" : "#64748b",
            "text-rotation": "autorotate",
            "text-background-color": dark ? "#0f172a" : "#ffffff",
            "text-background-opacity": 0.8,
          },
        },
        { selector: "edge[shared = 1]", style: { "line-color": "#f87171", width: 2.5 } },
        { selector: "node.hl", style: { "border-width": 5, "border-color": "#facc15" } },
        { selector: "edge.hl", style: { "line-color": "#facc15", width: 4 } },
        { selector: "node:selected", style: { "border-width": 4, "border-color": "#22d3ee" } },
      ],
      layout:
        layout === "breadthfirst"
          ? { name: "breadthfirst", roots: root ? [root] : undefined, spacingFactor: 1.1 }
          : layout === "concentric"
            ? { name: "concentric", minNodeSpacing: 25 }
            : { name: "cose", animate: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 80 },
    });
    cy.current.on("tap", "node", (evt) => {
      const node = data.nodes.find((n) => n.id === evt.target.id());
      if (node) select.current?.(node);
    });
    return () => {
      cy.current?.destroy();
      cy.current = null;
    };
  }, [data, highlight, layout, root]);

  return (
    <div>
      <div ref={container} style={{ height }} className="w-full rounded-md border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950" />
      <Legend types={[...new Set(data.nodes.map((n) => n.label))]} />
    </div>
  );
}

function Legend({ types }: { types: string[] }) {
  return (
    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400">
      {types.map((t) => (
        <span key={t} className="flex items-center gap-1">
          <span className="inline-block h-3 w-3 rounded-full" style={{ background: NODE_COLORS[t] ?? "#64748b" }} />
          {t}
        </span>
      ))}
      <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-full border-2 border-red-600" />flagged</span>
      <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded-full border-2 border-dashed border-amber-500" />pre-emptive</span>
      <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-red-400" />SHARED_* link</span>
      <span>Account size = risk</span>
    </div>
  );
}

export function NodeDetails({ node }: { node: GraphNode | null }) {
  if (!node) return <p className="text-sm text-slate-500">Click a node to see its details.</p>;
  const entries = Object.entries(node.props).filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && !v.length));
  return (
    <div className="text-sm">
      <div className="mb-2 font-semibold">{node.label}: {node.caption}</div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-slate-500">{k}</dt>
            <dd className="break-words">{Array.isArray(v) ? v.join(" | ") : typeof v === "number" ? +v.toFixed(4) : String(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
