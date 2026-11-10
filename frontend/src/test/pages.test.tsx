/** Smoke tests: every page renders with a mocked API and shows its key content. */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { AuthProvider } from "../auth/AuthContext";

const RESPONSES: Record<string, unknown> = {
  "/ready": { status: "ready", checks: { neo4j: { ok: true, version: "5.26" } } },
  "/api/v1/stats/overview": {
    kpis: { tx_24h: 120, tx_total: 50000, open_alerts: 7, active_rings: 3, accounts_at_risk: 12, pre_emptive: 4, flagged: 17 },
    alerts_by_day: [{ day: "2026-11-10", RING_DETECTED: 2 }],
    risk_distribution: [{ range: "0.0-0.1", accounts: 5 }],
    recent_transactions: [{ id: "T1", account_id: "A1", amount: 1200, channel: "UPI", location: "Pune, IN", timestamp: "2026-11-10T10:00:00Z", rule_score: 0, final_score: 3, decision: "ALLOW" }],
    metrics: { ingested_total: 5, ingest_rate_per_min: 5, latency_ms_p50: 70, latency_ms_p95: 300, queue_depth: 0, last_detection: null },
  },
  "/api/v1/rings": { total: 1, items: [{ ring_id: "R-abc123", status: "NEW", size: 5, density: 1, avg_risk: 0.4, shared_devices: 1, shared_cards: 0, shared_addresses: 0, shared_phones: 0, flagged_members: 1, total_volume: 1000, detected_at: "2026-11-10T10:00:00Z" }] },
  "/api/v1/alerts": { total: 1, items: [{ id: "x", type: "RING_DETECTED", severity: "HIGH", status: "OPEN", explanation: "5 accounts linked", created_at: "2026-11-10T10:00:00Z", entity_label: "Ring", entity_id: "R-abc123", assignee: null, notes: [] }] },
  "/api/v1/stats/comparison": {
    rules_only: { count: 3, sample: ["A1"] }, graph_only: { count: 90, sample: ["A2"] }, both: { count: 6, sample: ["A3"] },
    evaluation: {
      truth: { fraud_accounts: 108, known_flagged_excluded: 17 },
      account_level: { rules_only: { precision: 0.6, recall: 0.05, f1: 0.1, true_positives: 6, false_positives: 3, false_negatives: 102 } },
      ring_level: { found: 24, total: 24, by_type: { shared_device: "6/6" } },
    },
  },
  "/api/v1/stats/benchmark": { available: false },
  "/api/v1/stats/metrics": { ingested_total: 0, latency_ms_p50: null, latency_ms_p95: null, last_detection: null },
  "/api/v1/risk/accounts": [],
  "/api/v1/admin/users": [{ username: "admin", name: "Admin", role: "ADMIN", active: true }],
  "/api/v1/admin/api-keys": [],
  "/api/v1/admin/settings": {
    rules: { flag_threshold: 60 },
    propagation: { weights: { SHARED_DEVICE: 0.9 }, decay: 0.5, max_depth: 3, surface_threshold: 0.3 },
    detection: { algorithm: "louvain", interval_seconds: 60 },
    decision: { review_threshold: 40, block_threshold: 70 },
  },
  "/api/v1/admin/audit": { total: 1, items: [{ id: "1", at: "2026-11-10T10:00:00Z", actor: "admin", action: "LOGIN", target: "admin", details: {} }] },
};

function mockFetch(input: RequestInfo | URL) {
  const path = new URL(String(input)).pathname;
  const body = RESPONSES[path];
  return Promise.resolve(new Response(JSON.stringify(body ?? {}), { status: body === undefined ? 404 : 200 }));
}

function renderAt(path: string, role: "ADMIN" | "VIEWER" | null = "ADMIN") {
  if (role) {
    sessionStorage.setItem("fraudmesh.auth", JSON.stringify({
      tokens: { access_token: "a", refresh_token: "r" },
      user: { username: "tester", role },
    }));
  }
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn(mockFetch));
});
afterEach(() => vi.unstubAllGlobals());

describe("pages", () => {
  it("shows the login form when signed out", async () => {
    renderAt("/", null);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(await screen.findByText("all services ready")).toBeInTheDocument();
  });

  it.each([
    ["/", "Pre-emptive detections"],
    ["/rings", "R-abc123"],
    ["/alerts", "5 accounts linked"],
    ["/comparison", "Caught by graph only"],
    ["/performance", "Ingestion latency p50"],
    ["/explorer", "Graph Explorer"],
    ["/paths", "Path Finder"],
    ["/propagation", "Pre-emptive detections"],
    ["/admin", "API keys (ingestion clients)"],
    ["/audit", "LOGIN"],
  ])("renders %s", async (path, text) => {
    renderAt(path);
    await waitFor(() => expect(screen.getAllByText(text).length).toBeGreaterThan(0));
  });

  it("hides admin pages from viewers", async () => {
    renderAt("/admin", "VIEWER");
    expect(await screen.findByText("You need the ADMIN role to see this page.")).toBeInTheDocument();
    expect(screen.queryByText("Audit Log")).not.toBeInTheDocument();
  });
});
