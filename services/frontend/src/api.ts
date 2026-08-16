import type { EventItem, Job, StatsResponse, VideoEntry } from "./types";

const EVENTS_BASE = "/api/events";
const INGEST_BASE = "/api/ingest";

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export interface EventFilters {
  priority?: string;
  status?: string;
  category?: string;
  camera_id?: string;
  limit?: number;
  offset?: number;
}

export function listEvents(filters: EventFilters = {}): Promise<EventItem[]> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== "") params.set(k, String(v));
  });
  return fetch(`${EVENTS_BASE}/events?${params.toString()}`).then((r) => asJson<EventItem[]>(r));
}

export function getStats(): Promise<StatsResponse> {
  return fetch(`${EVENTS_BASE}/stats`).then((r) => asJson<StatsResponse>(r));
}

export function updateEventStatus(eventId: string, status: EventStatusInput): Promise<EventItem> {
  return fetch(`${EVENTS_BASE}/events/${encodeURIComponent(eventId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  }).then((r) => asJson<EventItem>(r));
}
type EventStatusInput = "new" | "acknowledged" | "dismissed";

export function listVideos(): Promise<VideoEntry[]> {
  return fetch(`${INGEST_BASE}/videos`).then((r) => asJson<VideoEntry[]>(r));
}

export function uploadVideo(file: File, onProgress?: (pct: number) => void): Promise<VideoEntry> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${INGEST_BASE}/uploads`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(`${xhr.status} ${xhr.statusText}: ${xhr.responseText}`));
      }
    };
    xhr.onerror = () => reject(new Error("upload failed"));
    xhr.send(form);
  });
}

export function startIngest(source: "library" | "upload", filename: string, cameraId?: string): Promise<Job> {
  return fetch(`${INGEST_BASE}/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, filename, camera_id: cameraId || undefined }),
  }).then((r) => asJson<Job>(r));
}

export function listJobs(): Promise<Job[]> {
  return fetch(`${INGEST_BASE}/jobs`).then((r) => asJson<Job[]>(r));
}

export function getJob(jobId: string): Promise<Job> {
  return fetch(`${INGEST_BASE}/jobs/${jobId}`).then((r) => asJson<Job>(r));
}
