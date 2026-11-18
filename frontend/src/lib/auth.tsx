import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, tokenStore } from "./api";
import type { Role, User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

/** Landing page per role. The server enforces permissions; this only picks a sensible home. */
export const HOME: Record<Role, string> = {
  SALESMAN: "/sales",
  ADMIN: "/admin/orders",
  PRODUCTION: "/production",
  OWNER: "/dashboard",
  AUDITOR: "/reports",
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  useEffect(() => {
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    window.addEventListener("ota:unauthorized", logout);
    return () => window.removeEventListener("ota:unauthorized", logout);
  }, [logout]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api<{ access_token: string; user: User }>("/auth/login", { form: { username, password } });
    tokenStore.set(res.access_token);
    setUser(res.user);
    return res.user;
  }, []);

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

export function useRole(): Role {
  const { user } = useAuth();
  if (!user) throw new Error("not logged in");
  return user.role;
}
