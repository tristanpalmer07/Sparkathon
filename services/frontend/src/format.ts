export function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "medium",
    });
  } catch {
    return iso;
  }
}

export function formatDuration(startIso: string, endIso: string): string {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let val = bytes / 1024;
  let i = 0;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

export function priorityClass(priority: string | null): string {
  switch (priority) {
    case "high":
      return "badge badge-high";
    case "medium":
      return "badge badge-medium";
    case "low":
      return "badge badge-low";
    default:
      return "badge badge-neutral";
  }
}

export function statusClass(status: string): string {
  switch (status) {
    case "new":
      return "badge badge-status-new";
    case "acknowledged":
      return "badge badge-status-ack";
    case "dismissed":
      return "badge badge-status-dismissed";
    default:
      return "badge badge-neutral";
  }
}

export function jobStatusClass(status: string): string {
  switch (status) {
    case "succeeded":
      return "badge badge-status-ack";
    case "failed":
      return "badge badge-high";
    case "queued":
      return "badge badge-neutral";
    default:
      return "badge badge-medium";
  }
}
