import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { auth } from "../api/endpoints";
import { ratings } from "../api/ratings";
import { getToken, setToken } from "../api/client";

export type Role = "researcher" | "rater";

interface AuthState {
  signedIn: boolean;
  /** Null until /auth/me has answered. Raters see only the rating screen. */
  role: Role | null;
  username: string | null;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [signedIn, setSignedIn] = useState<boolean>(() => getToken() !== null);
  const [role, setRole] = useState<Role | null>(null);
  const [username, setUsername] = useState<string | null>(null);

  useEffect(() => {
    if (!signedIn) { setRole(null); setUsername(null); return; }
    ratings.me().then((m) => { setRole(m.role); setUsername(m.username); })
      // An older backend has no /auth/me; treat the account as a researcher,
      // which is what every account was before roles existed.
      .catch(() => { setRole("researcher"); });
  }, [signedIn]);

  const signIn = useCallback(async (u: string, password: string) => {
    const { access_token } = await auth.login(u, password);
    setToken(access_token);
    setSignedIn(true);
  }, []);

  const signOut = useCallback(async () => {
    await auth.logout();
    setToken(null);
    setSignedIn(false);
  }, []);

  const value = useMemo(() => ({ signedIn, role, username, signIn, signOut }), [signedIn, role, username, signIn, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
