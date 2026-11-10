import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import type { Role } from "./api/client";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import Admin from "./pages/Admin";
import Alerts from "./pages/Alerts";
import Audit from "./pages/Audit";
import Comparison from "./pages/Comparison";
import GraphExplorer from "./pages/GraphExplorer";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import PathFinder from "./pages/PathFinder";
import Performance from "./pages/Performance";
import RiskPropagation from "./pages/RiskPropagation";
import { RingDetailPage, RingList } from "./pages/Rings";

function RequireAuth({ role = "VIEWER", children }: { role?: Role; children: ReactNode }) {
  const { user, can } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (!can(role)) return <p className="text-sm">You need the {role} role to see this page.</p>;
  return <>{children}</>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<Overview />} />
        <Route path="rings" element={<RingList />} />
        <Route path="rings/:id" element={<RingDetailPage />} />
        <Route path="explorer" element={<GraphExplorer />} />
        <Route path="paths" element={<PathFinder />} />
        <Route path="propagation" element={<RiskPropagation />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="comparison" element={<Comparison />} />
        <Route path="performance" element={<Performance />} />
        <Route path="admin" element={<RequireAuth role="ADMIN"><Admin /></RequireAuth>} />
        <Route path="audit" element={<RequireAuth role="ADMIN"><Audit /></RequireAuth>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
}
