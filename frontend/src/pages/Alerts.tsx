import { Fragment, useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { patch } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Badge, Button, Card, ErrorBox, inputClass, Loading, PageHeader, Table, Td, when } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useLive, type LiveEvent } from "../hooks/useLive";

interface Alert {
  id: string;
  type: string;
  severity: string;
  status: string;
  explanation: string;
  created_at: string;
  entity_label: string;
  entity_id: string;
  assignee: string | null;
  notes: string[];
}

function subjectLink(a: Alert) {
  if (a.entity_label === "Ring") return <Link className="text-blue-600 hover:underline dark:text-blue-400" to={`/rings/${a.entity_id}`}>{a.entity_id}</Link>;
  return <span>{a.entity_id}</span>;
}

export default function Alerts() {
  const { can, user } = useAuth();
  const [status, setStatus] = useState("OPEN");
  const [type, setType] = useState("");
  const [severity, setSeverity] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [fresh, setFresh] = useState(0);
  const qs = new URLSearchParams({ page_size: "100" });
  if (status) qs.set("status", status);
  if (type) qs.set("type", type);
  if (severity) qs.set("severity", severity);
  const { data, error, reload } = useApi<{ total: number; items: Alert[] }>(`/api/v1/alerts?${qs}`);

  const onEvent = useCallback((e: LiveEvent) => {
    if (e.event === "alert" || e.event === "alert_updated") {
      if (e.event === "alert") setFresh((n) => n + 1);
      void reload();
    }
  }, [reload]);
  useLive(onEvent);

  const update = async (id: string, body: Record<string, unknown>) => {
    await patch(`/api/v1/alerts/${id}`, body);
    setNote("");
    await reload();
  };

  return (
    <>
      <PageHeader title="Alerts" subtitle={fresh ? `${fresh} new alerts arrived while this page was open` : "Real-time alerts from rules, ring detection and risk propagation"} />
      <Card
        title={data ? `${data.total} alerts` : "Alerts"}
        actions={
          <div className="flex flex-wrap gap-2">
            <select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value)}>
              {["", "OPEN", "ACK", "RESOLVED"].map((s) => <option key={s} value={s}>{s || "Any status"}</option>)}
            </select>
            <select className={inputClass} value={type} onChange={(e) => setType(e.target.value)}>
              {["", "HIGH_RULE_SCORE", "RING_DETECTED", "PROPAGATED_RISK", "LINKED_TO_FRAUD"].map((s) => <option key={s} value={s}>{s ? s.replaceAll("_", " ") : "Any type"}</option>)}
            </select>
            <select className={inputClass} value={severity} onChange={(e) => setSeverity(e.target.value)}>
              {["", "CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => <option key={s} value={s}>{s || "Any severity"}</option>)}
            </select>
          </div>
        }
      >
        <ErrorBox error={error} />
        {!data ? <Loading /> : (
          <Table head={["Created", "Severity", "Type", "Subject", "Explanation", "Status", "Assignee", ""]}>
            {data.items.map((a) => (
              <Fragment key={a.id}>
                <tr>
                  <Td className="whitespace-nowrap">{when(a.created_at)}</Td>
                  <Td><Badge value={a.severity} /></Td>
                  <Td className="text-xs whitespace-nowrap">{a.type.replaceAll("_", " ")}</Td>
                  <Td className="font-mono text-xs">{subjectLink(a)}</Td>
                  <Td className="max-w-md text-xs">{a.explanation}</Td>
                  <Td><Badge value={a.status} /></Td>
                  <Td>{a.assignee ?? "–"}</Td>
                  <Td>
                    {can("ANALYST") && (
                      <Button variant="secondary" onClick={() => setOpen(open === a.id ? null : a.id)}>Manage</Button>
                    )}
                  </Td>
                </tr>
                {open === a.id && (
                  <tr>
                    <td colSpan={8} className="bg-slate-50 px-3 py-3 dark:bg-slate-950">
                      <div className="flex flex-wrap items-center gap-2">
                        {a.status === "OPEN" && <Button variant="secondary" onClick={() => update(a.id, { status: "ACK" })}>Acknowledge</Button>}
                        {a.status !== "RESOLVED" && <Button onClick={() => update(a.id, { status: "RESOLVED", note: note || undefined })}>Resolve</Button>}
                        <Button variant="secondary" onClick={() => update(a.id, { assignee: user?.username })}>Assign to me</Button>
                        <input className={`${inputClass} min-w-64 flex-1`} placeholder="Add a note" value={note} onChange={(e) => setNote(e.target.value)} />
                        <Button variant="secondary" disabled={!note} onClick={() => update(a.id, { note })}>Add note</Button>
                      </div>
                      {a.notes.length > 0 && (
                        <ul className="mt-2 list-disc pl-5 text-xs text-slate-600 dark:text-slate-400">
                          {a.notes.map((n, i) => <li key={i}>{n}</li>)}
                        </ul>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
