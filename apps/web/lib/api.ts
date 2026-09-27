import type { ProspectDocument } from "@/lib/documents";
import { tokenState } from "./session.ts";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "prospect.session";

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

let pendingToken: Promise<string> | null = null;

// Anonymous per-browser identity (see apps/api/app/auth.py). Only a signed, expiring session
// token is stored; storage credentials never reach the browser.
async function issue(path: string, token?: string): Promise<string | null> {
  const res = await fetch(`${API_URL}/api/v1${path}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  }).catch(() => null);
  if (res?.status === 429) {
    throw new ApiError(429, "rate_limited", "Too many requests. Wait a minute and try again.");
  }
  if (!res?.ok) return null;
  const { token: fresh } = (await res.json()) as { token: string };
  localStorage.setItem(TOKEN_KEY, fresh);
  return fresh;
}

function sessionToken(): Promise<string> {
  const saved = localStorage.getItem(TOKEN_KEY);
  const state = saved ? tokenState(saved, Date.now()) : "expired";
  if (saved && state === "valid") return Promise.resolve(saved);
  pendingToken ??= (async () => {
    // Past half its lifetime: swap it for a fresh one (same user, keeps the documents).
    const refreshed = saved && state === "refresh" ? await issue("/sessions/refresh", saved) : null;
    const token = refreshed ?? (await issue("/sessions"));
    if (!token) throw new ApiError(0, "session_failed", "Could not start a session");
    return token;
  })().finally(() => {
    pendingToken = null;
  });
  return pendingToken;
}

export async function api<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/v1${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${await sessionToken()}`,
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the Prospect API.");
  }
  if (res.status === 401) {
    // Stale session (APP_SECRET rotated, user removed): start a new one and retry once.
    localStorage.removeItem(TOKEN_KEY);
    if (!retried) return api<T>(path, init, true);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(
      res.status,
      body?.error?.code ?? "http_error",
      body?.error?.message ?? `Request failed (${res.status})`,
    );
  }
  return res.json() as Promise<T>;
}

/** Download an authenticated file (exports): the API needs the bearer token, a link cannot. */
export async function downloadFile(path: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/v1${path}`, {
    headers: { Authorization: `Bearer ${await sessionToken()}` },
  }).catch(() => null);
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
