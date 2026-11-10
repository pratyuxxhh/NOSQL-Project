import { useEffect, useState, type FormEvent } from "react";
import { del, patch, post, put } from "../api/client";
import { Badge, Button, Card, ErrorBox, inputClass, Loading, PageHeader, Table, Td, when } from "../components/ui";
import { useApi } from "../hooks/useApi";

type Settings = {
  rules: Record<string, number>;
  propagation: { weights: Record<string, number>; decay: number; max_depth: number; surface_threshold: number };
  detection: Record<string, number | string>;
  decision: Record<string, number>;
};

export default function Admin() {
  return (
    <>
      <PageHeader title="Administration" subtitle="Users and roles, API keys, scoring and detection settings" />
      <div className="space-y-4">
        <Users />
        <ApiKeys />
        <SettingsEditor />
      </div>
    </>
  );
}

function Users() {
  const { data, error, reload } = useApi<Record<string, unknown>[]>("/api/v1/admin/users");
  const [form, setForm] = useState({ username: "", name: "", role: "ANALYST", password: "" });
  const [message, setMessage] = useState<string | null>(null);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await post("/api/v1/admin/users", form);
      setForm({ username: "", name: "", role: "ANALYST", password: "" });
      setMessage(null);
      await reload();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  };
  const change = async (username: string, body: Record<string, unknown>) => {
    try {
      await patch(`/api/v1/admin/users/${username}`, body);
      await reload();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Card title="Users">
      <ErrorBox error={error ?? message} />
      {!data ? <Loading /> : (
        <Table head={["Username", "Name", "Role", "Active", ""]}>
          {data.map((u) => (
            <tr key={String(u.username)}>
              <Td className="font-mono">{String(u.username)}</Td>
              <Td>{String(u.name)}</Td>
              <Td>
                <select className={inputClass} value={String(u.role)} onChange={(e) => change(String(u.username), { role: e.target.value })}>
                  {["ADMIN", "ANALYST", "VIEWER"].map((r) => <option key={r}>{r}</option>)}
                </select>
              </Td>
              <Td>{u.active ? "yes" : "no"}</Td>
              <Td><Button variant="secondary" onClick={() => change(String(u.username), { active: !u.active })}>{u.active ? "Disable" : "Enable"}</Button></Td>
            </tr>
          ))}
        </Table>
      )}
      <form onSubmit={create} className="mt-3 flex flex-wrap gap-2">
        <input className={inputClass} placeholder="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
        <input className={inputClass} placeholder="Full name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <select className={inputClass} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
          {["ADMIN", "ANALYST", "VIEWER"].map((r) => <option key={r}>{r}</option>)}
        </select>
        <input className={inputClass} type="password" placeholder="Password (8+)" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required minLength={8} />
        <Button type="submit">Add user</Button>
      </form>
    </Card>
  );
}

function ApiKeys() {
  const { data, error, reload } = useApi<Record<string, unknown>[]>("/api/v1/admin/api-keys");
  const [name, setName] = useState("");
  const [created, setCreated] = useState<string | null>(null);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    const r = await post<{ key: string }>("/api/v1/admin/api-keys", { name });
    setCreated(r.key);
    setName("");
    await reload();
  };

  return (
    <Card title="API keys (ingestion clients)">
      <ErrorBox error={error} />
      {created && (
        <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950">
          Copy this key now; it will not be shown again: <code className="break-all">{created}</code>
        </div>
      )}
      {!data ? <Loading /> : (
        <Table head={["Name", "Prefix", "Limit / min", "Created", "Last used", "Status", ""]}>
          {data.map((k) => (
            <tr key={String(k.id)}>
              <Td>{String(k.name)}</Td>
              <Td className="font-mono">{String(k.prefix)}…</Td>
              <Td className="tabular-nums">{String(k.rate_limit_per_min)}</Td>
              <Td>{when(k.created_at)}</Td>
              <Td>{when(k.last_used_at)}</Td>
              <Td><Badge value={k.active ? "ALLOW" : "BLOCK"} /></Td>
              <Td>{Boolean(k.active) && <Button variant="danger" onClick={async () => { await del(`/api/v1/admin/api-keys/${k.id}`); await reload(); }}>Revoke</Button>}</Td>
            </tr>
          ))}
        </Table>
      )}
      <form onSubmit={create} className="mt-3 flex gap-2">
        <input className={inputClass} placeholder="Client name, e.g. card-switch" value={name} onChange={(e) => setName(e.target.value)} required />
        <Button type="submit">Create key</Button>
      </form>
    </Card>
  );
}

function NumberField({ label, value, onChange, step = 1 }: { label: string; value: number; onChange: (v: number) => void; step?: number }) {
  return (
    <label className="block text-xs">
      <span className="text-slate-500">{label.replaceAll("_", " ")}</span>
      <input type="number" step={step} className={`${inputClass} mt-0.5 block w-full`} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function SettingsEditor() {
  const { data, error } = useApi<Settings>("/api/v1/admin/settings");
  const [draft, setDraft] = useState<Settings | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => setDraft(data), [data]);
  if (!draft) return <Card title="Settings">{error ? <ErrorBox error={error} /> : <Loading />}</Card>;

  const save = async () => {
    try {
      setDraft(await put<Settings>("/api/v1/admin/settings", draft));
      setMessage("Saved. New settings apply to the next transaction and the next detection cycle.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  };
  const set = <K extends keyof Settings>(section: K, key: string, value: unknown) =>
    setDraft({ ...draft, [section]: { ...draft[section], [key]: value } });

  return (
    <Card title="Settings" actions={<Button onClick={save}>Save settings</Button>}>
      {message && <p className="mb-3 text-sm">{message}</p>}
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-semibold">Rule thresholds (baseline)</h3>
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(draft.rules).map(([k, v]) => <NumberField key={k} label={k} value={v} onChange={(n) => set("rules", k, n)} />)}
          </div>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Risk propagation</h3>
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(draft.propagation.weights).map(([k, v]) => (
              <NumberField key={k} label={`weight ${k}`} value={v} step={0.05}
                onChange={(n) => set("propagation", "weights", { ...draft.propagation.weights, [k]: n })} />
            ))}
            <NumberField label="decay" value={draft.propagation.decay} step={0.05} onChange={(n) => set("propagation", "decay", n)} />
            <NumberField label="max_depth" value={draft.propagation.max_depth} onChange={(n) => set("propagation", "max_depth", n)} />
            <NumberField label="surface_threshold" value={draft.propagation.surface_threshold} step={0.05} onChange={(n) => set("propagation", "surface_threshold", n)} />
          </div>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Ring detection</h3>
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-xs">
              <span className="text-slate-500">algorithm</span>
              <select className={`${inputClass} mt-0.5 block w-full`} value={String(draft.detection.algorithm)} onChange={(e) => set("detection", "algorithm", e.target.value)}>
                <option value="louvain">Louvain</option>
                <option value="lpa">Label Propagation</option>
              </select>
            </label>
            {Object.entries(draft.detection).filter(([k]) => k !== "algorithm").map(([k, v]) => (
              <NumberField key={k} label={k} value={Number(v)} step={k.includes("ratio") || k.includes("threshold") ? 0.05 : 1} onChange={(n) => set("detection", k, n)} />
            ))}
          </div>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold">Decision thresholds (final score 0–100)</h3>
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(draft.decision).map(([k, v]) => <NumberField key={k} label={k} value={v} onChange={(n) => set("decision", k, n)} />)}
          </div>
        </div>
      </div>
    </Card>
  );
}
