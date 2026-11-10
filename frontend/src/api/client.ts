export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Role = "ADMIN" | "ANALYST" | "VIEWER";

export interface User {
  username: string;
  name?: string;
  role: Role;
}

interface Tokens {
  access_token: string;
  refresh_token: string;
}

const STORAGE_KEY = "fraudmesh.auth";

// Tokens live in memory, mirrored to sessionStorage so a page reload keeps you logged in
// (cleared when the tab closes).
let tokens: Tokens | null = null;
try {
  const saved = sessionStorage.getItem(STORAGE_KEY);
  if (saved) tokens = JSON.parse(saved).tokens;
} catch {
  tokens = null;
}

export function savedUser(): User | null {
  try {
    const saved = sessionStorage.getItem(STORAGE_KEY);
    return saved ? (JSON.parse(saved).user as User) : null;
  } catch {
    return null;
  }
}

function store(next: Tokens | null, user?: User | null) {
  tokens = next;
  try {
    if (next) sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ tokens: next, user: user ?? savedUser() }));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable: memory only */
  }
}

export function accessToken(): string | null {
  return tokens?.access_token ?? null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let onLogout: () => void = () => {};
export function setLogoutHandler(fn: () => void) {
  onLogout = fn;
}

async function refresh(): Promise<boolean> {
  if (!tokens) return false;
  const response = await fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  });
  if (!response.ok) return false;
  store(await response.json());
  return true;
}

/** Call the API with the access token; on 401, refresh once and retry. */
export async function api<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (tokens) headers.set("Authorization", `Bearer ${tokens.access_token}`);
  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (response.status === 401 && retry && tokens) {
    if (await refresh()) return api<T>(path, options, false);
    store(null);
    onLogout();
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export async function login(username: string, password: string): Promise<User> {
  const response = await fetch(`${API_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    throw new ApiError(response.status, response.status === 429 ? "Too many attempts, wait a minute" : "Invalid username or password");
  }
  const body = await response.json();
  store(body, body.user);
  return body.user as User;
}

export function logout() {
  store(null);
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });

// --- Shared response types ---------------------------------------------------

export interface GraphNode {
  id: string;
  key: string;
  label: string;
  caption: string;
  props: Record<string, unknown>;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  props: Record<string, unknown>;
}
export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ReadyResponse {
  status: "ready" | "not_ready";
  checks: Record<string, { ok: boolean; version?: string; error?: string }>;
}

export async function fetchReady(): Promise<ReadyResponse> {
  const response = await fetch(`${API_URL}/ready`);
  return (await response.json()) as ReadyResponse;
}
