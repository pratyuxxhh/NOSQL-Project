import { useState } from "react";
import { Button, Card, ErrorBox, inputClass, Loading, PageHeader, Table, Td, when } from "../components/ui";
import { useApi } from "../hooks/useApi";

interface Entry {
  id: string;
  at: string;
  actor: string;
  action: string;
  target: string;
  details: Record<string, unknown>;
}

const ACTIONS = ["", "LOGIN", "FLAG_ACCOUNT", "RING_STATUS", "RUN_DETECTION", "UPDATE_ALERT", "UPDATE_SETTINGS",
  "CREATE_USER", "UPDATE_USER", "CREATE_API_KEY", "REVOKE_API_KEY"];

export default function Audit() {
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const { data, error } = useApi<{ total: number; items: Entry[] }>(
    `/api/v1/admin/audit?page=${page}&page_size=50${action ? `&action=${action}` : ""}`,
  );

  return (
    <>
      <PageHeader title="Audit log" subtitle="Every analyst and admin action, newest first" />
      <Card
        title={data ? `${data.total} entries` : "Entries"}
        actions={
          <select className={inputClass} value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
            {ACTIONS.map((a) => <option key={a} value={a}>{a ? a.replaceAll("_", " ") : "All actions"}</option>)}
          </select>
        }
      >
        <ErrorBox error={error} />
        {!data ? <Loading /> : (
          <Table head={["When", "Who", "Action", "Target", "Details"]}>
            {data.items.map((e) => (
              <tr key={e.id}>
                <Td className="whitespace-nowrap">{when(e.at)}</Td>
                <Td>{e.actor}</Td>
                <Td className="text-xs">{e.action}</Td>
                <Td className="font-mono text-xs">{e.target}</Td>
                <Td className="font-mono text-xs break-all">{Object.keys(e.details).length ? JSON.stringify(e.details) : ""}</Td>
              </tr>
            ))}
          </Table>
        )}
        {data && data.total > 50 && (
          <div className="mt-3 flex gap-2">
            <Button variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <Button variant="secondary" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        )}
      </Card>
    </>
  );
}
