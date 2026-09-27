import type { ProspectDocument } from "@/lib/documents";
import { type SessionInfo, sessionState } from "./session.ts";

// Same origin: next.config.ts proxies /api/v1 to the API, so the HttpOnly session cookie is
// first-party and is sent automatically. JavaScript never sees the session token.
const API = "/api/v1";
const CSRF_HEADER = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD"]);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export type SignedUpload = {
  url: string;
  method: "PUT";
  headers: Record<string, string>;
  expires_at: string;
};
export type DocumentUpload = { document: ProspectDocument; upload: SignedUpload };

// Before P1 the bearer token sat in localStorage, readable by any script. Take it out now and,
// once, trade it for a cookie session of the same user (the refresh also revokes it), so
// earlier uploads stay reachable.
let legacyToken: string | null = null;
try {
  legacyToken = globalThis.localStorage?.getItem("prospect.session") ?? null;
  globalThis.localStorage?.removeItem("prospect.session");
} catch {
  // storage disabled: nothing was stored there either
}

// The session's times and CSRF token, in memory only (a reload asks /sessions/current again).
let session: SessionInfo | null = null;
let pending: Promise<SessionInfo> | null = null;

async function issue(path: string, headers: Record<string, string> = {}) {
  const res = await fetch(`${API}${path}`, { method: "POST", headers }).catch(() => null);
  if (res?.status === 429) {
    throw new ApiError(429, "rate_limited", "Too many requests. Wait a minute and try again.");
  }
  return res?.ok ? ((await res.json()) as SessionInfo) : null;
}

async function current(): Promise<SessionInfo | null> {
  const res = await fetch(`${API}/sessions/current`).catch(() => null);
  return res?.ok ? ((await res.json()) as SessionInfo) : null;
}

/** The anonymous per-browser session: reuse the cookie's, refresh it past half-life, or start one. */
function ensureSession(): Promise<SessionInfo> {
  if (session && sessionState(session, Date.now()) === "valid") return Promise.resolve(session);
  pending ??= (async () => {
    let info = session ?? (await current());
    if (!info && legacyToken) {
      const token = legacyToken;
      legacyToken = null;
      info = await issue("/sessions/refresh", { Authorization: `Bearer ${token}` });
    }
    const state = info ? sessionState(info, Date.now()) : "expired";
    // Past half its lifetime: swap it for a fresh one (same user, keeps the documents).
    if (info && state === "refresh") {
      info = await issue("/sessions/refresh", { [CSRF_HEADER]: info.csrf_token });
    } else if (state === "expired") info = null;
    session = info ?? (await issue("/sessions"));
    if (!session) throw new ApiError(0, "session_failed", "Could not start a session");
    return session;
  })().finally(() => {
    pending = null;
  });
  return pending;
}

async function send(path: string, init: RequestInit): Promise<Response> {
  const { csrf_token } = await ensureSession();
  const unsafe = !SAFE_METHODS.has((init.method ?? "GET").toUpperCase());
  try {
    return await fetch(`${API}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(unsafe ? { [CSRF_HEADER]: csrf_token } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the Prospect API.");
  }
}

async function errorOf(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => null);
  return new ApiError(
    res.status,
    body?.error?.code ?? "http_error",
    body?.error?.message ?? `Request failed (${res.status})`,
  );
}

export async function api<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  const res = await send(path, init);
  if (!res.ok) {
    const error = await errorOf(res);
    // Session gone (expired, revoked, secret rotated) or replaced in another tab: start over once.
    if (!retried && (res.status === 401 || error.code === "csrf_failed")) {
      session = null;
      return api<T>(path, init, true);
    }
    throw error;
  }
  return (res.status === 204 ? undefined : res.json()) as Promise<T>;
}

/** Download an authenticated file (exports) and hand it to the browser as a download. */
export async function downloadFile(path: string): Promise<void> {
  await ensureSession();
  const res = await fetch(`${API}${path}`).catch(() => null);
  if (!res?.ok) throw new ApiError(res?.status ?? 0, "download_failed", "The export failed.");
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1];
  const url = URL.createObjectURL(await res.blob());
  const link = Object.assign(document.createElement("a"), { href: url, download: name ?? "" });
  link.click();
  URL.revokeObjectURL(url);
}

/** PUT a file to a signed URL, reporting real byte progress (fetch cannot report uploads). */
export function putWithProgress(
  upload: SignedUpload,
  file: File,
  onProgress: (loaded: number, total: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(upload.method, upload.url);
    for (const [name, value] of Object.entries(upload.headers)) xhr.setRequestHeader(name, value);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total);
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new ApiError(xhr.status, "storage_error", "The file could not be stored."));
    xhr.onerror = () => reject(new ApiError(0, "network_error", "The upload was interrupted."));
    xhr.send(file);
  });
}
