import { useEffect, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { fetchReady, type ReadyResponse } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Button, ErrorBox, inputClass } from "../components/ui";
import { useTheme } from "../components/Layout";

export default function Login() {
  const { user, login } = useAuth();
  useTheme();
  const [username, setUsername] = useState("analyst");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState<ReadyResponse | null>(null);

  useEffect(() => {
    fetchReady().then(setReady).catch(() => setReady(null));
  }, []);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
        <div>
          <h1 className="text-2xl font-bold">FraudMesh</h1>
          <p className="text-sm text-slate-500">Graph-based fraud ring detection</p>
        </div>
        <label className="block text-sm">
          Username
          <input className={`${inputClass} mt-1 w-full`} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label className="block text-sm">
          Password
          <input className={`${inputClass} mt-1 w-full`} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        <ErrorBox error={error} />
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
        <p className="text-xs text-slate-500">
          System:{" "}
          {ready ? (
            <span className={ready.status === "ready" ? "text-green-600" : "text-red-600"}>
              {ready.status === "ready" ? "all services ready" : "not ready (" + Object.entries(ready.checks).filter(([, c]) => !c.ok).map(([k]) => k).join(", ") + ")"}
            </span>
          ) : (
            <span className="text-red-600">backend unreachable</span>
          )}
        </p>
      </form>
    </main>
  );
}
