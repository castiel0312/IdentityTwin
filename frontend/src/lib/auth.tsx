import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
import type {
  AuthSession,
  ConsoleRole,
  DevHeaders,
  DevPersonaId,
} from "./auth-types";
import {
  SESSION_STORAGE_KEY,
  DEV_PERSONAS,
  DEV_MERCHANT_ID,
  DEV_ANALYST_ID,
  DEV_MERCHANT_USER_ID,
} from "./auth-types";

interface AuthContextValue {
  session: AuthSession | null;
  isAuthenticated: boolean;
  signInWithPersona: (id: DevPersonaId) => Promise<void>;
  signInWithToken: (token: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRole(value: unknown): value is ConsoleRole {
  return value === "merchant" || value === "analyst" || value === "admin";
}

function readStoredSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) return null;
    const headers = parsed.devHeaders;
    if (typeof parsed.token !== "string" || !parsed.token) return null;
    if (typeof parsed.label !== "string") return null;
    if (!isRole(parsed.role)) return null;
    if (!isRecord(headers)) return null;
    const devHeaders: DevHeaders = {
      "X-Dev-Role": String(headers["X-Dev-Role"] ?? parsed.role),
      "X-Dev-Merchant-Id": String(headers["X-Dev-Merchant-Id"] ?? DEV_MERCHANT_ID),
      "X-Dev-User-Id": String(headers["X-Dev-User-Id"] ?? DEV_MERCHANT_USER_ID),
    };
    return {
      token: parsed.token,
      label: parsed.label,
      role: parsed.role,
      merchantId:
        typeof parsed.merchantId === "string"
          ? parsed.merchantId
          : devHeaders["X-Dev-Merchant-Id"],
      developmentOnly: parsed.developmentOnly !== false,
      devHeaders,
    };
  } catch {
    return null;
  }
}

function writeStoredSession(session: AuthSession | null): void {
  if (typeof window === "undefined") return;
  if (session) {
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  } else {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  }
}

function tokenCandidate(token: string): AuthSession {
  const persona = DEV_PERSONAS.find((candidate) => candidate.token === token);
  if (persona) {
    return {
      token: persona.token,
      label: persona.label,
      role: persona.role,
      merchantId: persona.devHeaders["X-Dev-Merchant-Id"],
      developmentOnly: true,
      devHeaders: { ...persona.devHeaders },
    };
  }

  const role: ConsoleRole = token.toLowerCase().includes("analyst") ? "analyst" : "merchant";
  return {
    token,
    label: "Bearer session",
    role,
    merchantId: DEV_MERCHANT_ID,
    developmentOnly: token.startsWith("dev-"),
    devHeaders: {
      "X-Dev-Role": role,
      "X-Dev-Merchant-Id": DEV_MERCHANT_ID,
      "X-Dev-User-Id": role === "analyst" ? DEV_ANALYST_ID : DEV_MERCHANT_USER_ID,
    },
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(() => readStoredSession());

  const persist = useCallback((next: AuthSession | null) => {
    writeStoredSession(next);
    setSession(next);
  }, []);

  const signInWithPersona = useCallback(
    async (id: DevPersonaId) => {
      const persona = DEV_PERSONAS.find((candidate) => candidate.id === id);
      if (!persona) throw new Error("Unknown development persona.");
      const candidate: AuthSession = {
        token: persona.token,
        label: persona.label,
        role: persona.role,
        merchantId: persona.devHeaders["X-Dev-Merchant-Id"],
        developmentOnly: true,
        devHeaders: { ...persona.devHeaders },
      };
      await api.systemContext(candidate);
      persist(candidate);
    },
    [persist],
  );

  const signInWithToken = useCallback(
    async (token: string) => {
      const trimmed = token.trim();
      if (!trimmed) throw new Error("A bearer token is required.");
      const candidate = tokenCandidate(trimmed);
      const context = await api.systemContext(candidate);
      const role = isRole(context.principal.role) ? context.principal.role : candidate.role;
      const verified: AuthSession = {
        ...candidate,
        role,
        merchantId: context.principal.merchant_id,
        label:
          candidate.label === "Bearer session"
            ? context.principal.username || candidate.label
            : candidate.label,
        devHeaders: {
          ...candidate.devHeaders,
          "X-Dev-Role": role,
        },
      };
      persist(verified);
    },
    [persist],
  );

  const signOut = useCallback(() => {
    persist(null);
  }, [persist]);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isAuthenticated: Boolean(session),
      signInWithPersona,
      signInWithToken,
      signOut,
    }),
    [session, signInWithPersona, signInWithToken, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within an AuthProvider.");
  return context;
}

export {
  type AuthSession,
  type ConsoleRole,
  type DevHeaders,
  type DevPersona,
  type DevPersonaId,
  SESSION_STORAGE_KEY,
  DEV_PERSONAS,
  DEV_MERCHANT_ID,
  DEV_ANALYST_ID,
  DEV_ALT_MERCHANT_ID,
  DEV_MERCHANT_USER_ID,
} from "./auth-types";
