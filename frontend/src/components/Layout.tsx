import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import type { Role } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const NAV: { to: string; label: string; role: Role }[] = [
  { to: "/", label: "Overview", role: "VIEWER" },
  { to: "/rings", label: "Rings", role: "VIEWER" },
  { to: "/explorer", label: "Graph Explorer", role: "VIEWER" },
  { to: "/paths", label: "Path Finder", role: "VIEWER" },
  { to: "/propagation", label: "Risk Propagation", role: "VIEWER" },
  { to: "/alerts", label: "Alerts", role: "VIEWER" },
  { to: "/comparison", label: "Rules vs Graph", role: "VIEWER" },
  { to: "/performance", label: "Performance", role: "VIEWER" },
  { to: "/admin", label: "Admin", role: "ADMIN" },
  { to: "/audit", label: "Audit Log", role: "ADMIN" },
];

function initialDark(): boolean {
  try {
    const saved = localStorage.getItem("fraudmesh.theme");
    if (saved) return saved === "dark";
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export function useTheme() {
  const [dark, setDark] = useState(initialDark);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("fraudmesh.theme", dark ? "dark" : "light");
    } catch {
      /* ignore */
    }
  }, [dark]);
  return [dark, setDark] as const;
}

export function Layout() {
  const { user, logout, can } = useAuth();
  const [dark, setDark] = useTheme();
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b border-slate-200 bg-white md:sticky md:top-0 md:h-screen md:w-56 md:shrink-0 md:border-r md:border-b-0 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between px-4 py-3">
          <div>
            <div className="text-lg font-bold">FraudMesh</div>
            <div className="text-xs text-slate-500">Fraud ring detection</div>
          </div>
          <button className="rounded border border-slate-300 px-2 py-1 text-sm md:hidden dark:border-slate-700" onClick={() => setOpen(!open)} aria-label="Menu">
            ☰
          </button>
        </div>
        <nav className={`${open ? "block" : "hidden"} px-2 pb-3 md:block`}>
          {NAV.filter((item) => can(item.role)).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `block rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-blue-600 text-white" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="flex items-center justify-end gap-3 border-b border-slate-200 bg-white px-4 py-2 text-sm dark:border-slate-800 dark:bg-slate-900">
          <button className="rounded border border-slate-300 px-2 py-1 dark:border-slate-700" onClick={() => setDark(!dark)}>
            {dark ? "Light mode" : "Dark mode"}
          </button>
          <span className="text-slate-600 dark:text-slate-400">
            {user?.username} <span className="text-xs">({user?.role})</span>
          </span>
          <button className="rounded border border-slate-300 px-2 py-1 dark:border-slate-700" onClick={logout}>
            Log out
          </button>
        </header>
        <main className="mx-auto max-w-7xl p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
