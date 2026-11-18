/**
 * Thin fetch wrapper for the FastAPI backend.
 * - Adds the bearer token.
 * - Turns the backend's error envelope {error:{code,message,details}} into ApiError.
 * - Money and quantities arrive as exact decimal STRINGS; we never do arithmetic on them here.
 */
const TOKEN_KEY = "ota.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

type Options = { method?: string; body?: unknown; form?: Record<string, string>; params?: Record<string, unknown> };

function buildUrl(path: string, params?: Record<string, unknown>): string {
  const url = new URL(`/api${path}`, window.location.origin);
  Object.entries(params ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  });
  return url.pathname + url.search;
}

async function raise(res: Response): Promise<never> {
  let code = "http_error";
  let message = `Request failed (${res.status})`;
  let details: Record<string, unknown> = {};
  try {
    const body = await res.json();
    if (body?.error) ({ code, message, details = {} } = body.error);
    else if (body?.detail) message = typeof body.detail === "string" ? body.detail : message;
  } catch {
    /* non-JSON error body */
  }
  if (res.status === 401) window.dispatchEvent(new Event("ota:unauthorized"));
  throw new ApiError(res.status, code, message, details);
}

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) {
    body = new URLSearchParams(opts.form);
    headers["Content-Type"] = "application/x-www-form-urlencoded";
  } else if (opts.body !== undefined) {
    body = JSON.stringify(opts.body);
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(buildUrl(path, opts.params), { method: opts.method ?? (body ? "POST" : "GET"), headers, body });
  if (!res.ok) return raise(res);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/** Download a protected file (PDF/CSV/XLSX) with the auth header and save it. */
export async function download(path: string, params: Record<string, unknown> = {}): Promise<void> {
  const token = tokenStore.get();
  const res = await fetch(buildUrl(path, params), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) return raise(res);
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "download";
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
