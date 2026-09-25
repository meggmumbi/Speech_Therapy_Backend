import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { auth } from "../api/endpoints";
import { getToken, setToken } from "../api/client";

interface AuthState {
  signedIn: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [signedIn, setSignedIn] = useState<boolean>(() => getToken() !== null);

  const signIn = useCallback(async (username: string, password: string) => {
    const { access_token } = await auth.login(username, password);
    setToken(access_token);
    setSignedIn(true);
  }, []);

  const signOut = useCallback(async () => {
    await auth.logout();
    setToken(null);
    setSignedIn(false);
  }, []);

  const value = useMemo(() => ({ signedIn, signIn, signOut }), [signedIn, signIn, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
