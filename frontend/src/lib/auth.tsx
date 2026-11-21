import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, clearLegacyToken, hasSession } from "./api";
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

  // Session expired or revoked: forget the user locally (the server already rejected the cookie).
  const dropSession = useCallback(() => setUser(null), []);

  // Sign out: the server clears the httpOnly cookie, which this code cannot touch itself.
  const logout = useCallback(() => {
    setUser(null);
    api<void>("/auth/logout", { method: "POST" }).catch(() => { /* already signed out */ });
  }, []);

  useEffect(() => {
    clearLegacyToken();
    if (!hasSession()) {
      setLoading(false);
      return;
    }
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    window.addEventListener("ota:unauthorized", dropSession);
    return () => window.removeEventListener("ota:unauthorized", dropSession);
  }, [dropSession]);

  const login = useCallback(async (username: string, password: string) => {
    // The server sets the session cookie; the returned access_token is for API clients and is ignored here.
    const res = await api<{ user: User }>("/auth/login", { form: { username, password } });
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
