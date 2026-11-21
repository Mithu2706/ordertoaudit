/**
 * Thin fetch wrapper for the FastAPI backend.
 * - The session is an httpOnly cookie set by the server: this code never sees or stores the token.
 *   Writes echo the readable CSRF cookie in X-CSRF-Token (double-submit), which another site
 *   cannot do.
 * - Turns the backend's error envelope {error:{code,message,details}} into ApiError.
 * - Money and quantities arrive as exact decimal STRINGS; we never do arithmetic on them here.
 */
const CSRF_COOKIE = "ota_csrf";
const LEGACY_TOKEN_KEY = "ota.token"; // tokens were kept in localStorage before cookie sessions

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

/** True when the browser holds a session (the readable CSRF cookie is set alongside it). */
export function hasSession(): boolean {
  return document.cookie.split("; ").some((c) => c.startsWith(`${CSRF_COOKIE}=`));
}

function csrfToken(): string {
  const raw = document.cookie.split("; ").find((c) => c.startsWith(`${CSRF_COOKIE}=`));
  return raw ? decodeURIComponent(raw.slice(CSRF_COOKIE.length + 1)) : "";
}

/** Remove a token left in localStorage by older versions of the app. */
export function clearLegacyToken(): void {
  try { localStorage.removeItem(LEGACY_TOKEN_KEY); } catch { /* storage unavailable */ }
}

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
  let body: BodyInit | undefined;
  if (opts.form) {
    body = new URLSearchParams(opts.form);
    headers["Content-Type"] = "application/x-www-form-urlencoded";
  } else if (opts.body !== undefined) {
    body = JSON.stringify(opts.body);
    headers["Content-Type"] = "application/json";
  }
  const method = opts.method ?? (body ? "POST" : "GET");
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  const res = await fetch(buildUrl(path, opts.params), { method, headers, body, credentials: "same-origin" });
  if (!res.ok) return raise(res);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/** Download a protected file (PDF/CSV/XLSX) with the session cookie and save it. */
export async function download(path: string, params: Record<string, unknown> = {}): Promise<void> {
  const res = await fetch(buildUrl(path, params), { credentials: "same-origin" });
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
