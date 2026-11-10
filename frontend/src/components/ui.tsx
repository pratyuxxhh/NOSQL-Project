import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Card({ title, actions, children, className = "" }: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 ${className}`}>
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="font-semibold">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Kpi({ label, value, hint, tone = "default" }: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "default" | "danger" | "warning";
}) {
  const color = tone === "danger" ? "text-red-600 dark:text-red-400" : tone === "warning" ? "text-amber-600 dark:text-amber-400" : "";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <div className="text-sm text-slate-500 dark:text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${color}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

const BADGE: Record<string, string> = {
  CRITICAL: "bg-red-600 text-white",
  HIGH: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  MEDIUM: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  LOW: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  OPEN: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  ACK: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  RESOLVED: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  NEW: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  UNDER_REVIEW: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  CONFIRMED_FRAUD: "bg-red-600 text-white",
  FALSE_POSITIVE: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  ALLOW: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  REVIEW: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  BLOCK: "bg-red-600 text-white",
};

export function Badge({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium whitespace-nowrap ${BADGE[value] ?? BADGE.LOW}`}>
      {value.replaceAll("_", " ")}
    </span>
  );
}

export function Button({ variant = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger";
}) {
  const styles = {
    primary: "bg-blue-600 text-white hover:bg-blue-700 disabled:bg-blue-400",
    secondary: "border border-slate-300 bg-white hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800",
    danger: "bg-red-600 text-white hover:bg-red-700 disabled:bg-red-400",
  }[variant];
  return <button className={`rounded-md px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed ${styles} ${className}`} {...props} />;
}

export const inputClass =
  "rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300">{error}</div>;
}

export function Loading() {
  return <p className="text-sm text-slate-500">Loading…</p>;
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-xs text-slate-500 uppercase dark:border-slate-800">
          <tr>{head.map((h, i) => <th key={i} className="px-2 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">{children}</tbody>
      </table>
    </div>
  );
}

export function Td({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`px-2 py-1.5 ${className}`}>{children}</td>;
}

export const pct = (v: unknown) => (typeof v === "number" ? `${(v * 100).toFixed(0)}%` : "–");
export const money = (v: unknown) => (typeof v === "number" ? `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "–");
export const when = (v: unknown) => (typeof v === "string" ? new Date(v).toLocaleString() : "–");
