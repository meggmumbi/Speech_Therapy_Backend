/**
 * One fetch wrapper for every backend call.
 *
 * The backend is FastAPI: errors arrive as `{"detail": "..."}` or, for
 * validation, `{"detail": [{"msg": "..."}]}`. Surfacing that text is the
 * difference between "409" and "participant_code P21 is already enrolled",
 * and the second is the one a researcher can act on.
 */

export const API_BASE: string = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api/";
const BASE = API_BASE;
const TOKEN_KEY = "console.token";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: the session simply does not persist */
  }
}

function detailOf(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      const msgs = d
        .map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : null))
        .filter(Boolean);
      if (msgs.length) return msgs.join("; ");
    }
  }
  return `HTTP ${status}`;
}

export async function api<T>(
  path: string,
  init: RequestInit & { json?: unknown; query?: Record<string, string | number | boolean | undefined> } = {},
): Promise<T> {
  const { json, query, headers, ...rest } = init;
  let url = BASE + path.replace(/^\//, "");
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) if (v !== undefined) qs.set(k, String(v));
    url += (url.includes("?") ? "&" : "?") + qs.toString();
  }
  const token = getToken();
  const res = await fetch(url, {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  if (!res.ok) {
    if (res.status === 401) setToken(null);
    throw new ApiError(res.status, detailOf(body, res.status));
  }
  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
