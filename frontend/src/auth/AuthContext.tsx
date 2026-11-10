import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { login as apiLogin, logout as apiLogout, savedUser, setLogoutHandler, type Role, type User } from "../api/client";

const RANK: Record<Role, number> = { VIEWER: 1, ANALYST: 2, ADMIN: 3 };

interface AuthState {
  user: User | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  can: (role: Role) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(savedUser);

  const logout = useCallback(() => {
    apiLogout();
    setUser(null);
  }, []);

  useEffect(() => setLogoutHandler(() => setUser(null)), []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      login: async (username, password) => setUser(await apiLogin(username, password)),
      logout,
      can: (role) => !!user && RANK[user.role] >= RANK[role],
    }),
    [user, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
