import type { ProspectDocument } from "@/lib/documents";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "prospect.session";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
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

// Anonymous per-browser identity (see apps/api/app/auth.py). Only a signed user id is stored;
// storage credentials never reach the browser.
function sessionToken(): Promise<string> {
  const saved = localStorage.getItem(TOKEN_KEY);
  if (saved) return Promise.resolve(saved);
  pendingToken ??= fetch(`${API_URL}/api/v1/sessions`, { method: "POST" })
    .then(async (res) => {
      if (!res.ok) throw new ApiError(res.status, "session_failed", "Could not start a session");
      const { token } = (await res.json()) as { token: string };
      localStorage.setItem(TOKEN_KEY, token);
      return token;
    })
    .finally(() => {
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
