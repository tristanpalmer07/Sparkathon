import { useState } from "react";
import { updateEventStatus } from "../api";
import type { EventItem, EventStatus } from "../types";
import { formatDateTime, formatDuration, priorityClass, statusClass } from "../format";

export default function EventDetailDrawer({
  event,
  onClose,
  onStatusChanged,
}: {
  event: EventItem;
  onClose: () => void;
  onStatusChanged: (updated: EventItem) => void;
}) {
  const [updating, setUpdating] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function setStatus(status: EventStatus) {
    setUpdating(true);
    setErr(null);
    try {
      const updated = await updateEventStatus(event.event_id, status);
      onStatusChanged(updated);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setUpdating(false);
    }
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <h2>{event.trigger_type ?? "Event"}</h2>
            <div className="drawer-subtitle">
              <code>{event.camera_id}</code> · {formatDateTime(event.start_time)}
            </div>
          </div>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="drawer-badges">
          <span className={priorityClass(event.priority)}>{event.priority ?? "unknown"} priority</span>
          <span className={statusClass(event.status)}>{event.status}</span>
          {event.category && <span className="badge badge-neutral">{event.category}</span>}
        </div>

        {event.clip_reference ? (
          <video className="clip-player" src={event.clip_reference} controls preload="metadata" />
        ) : (
          <div className="no-clip">No clip reference available for this event.</div>
        )}

        <dl className="detail-grid">
          <dt>Window</dt>
          <dd>
            {formatDateTime(event.start_time)} → {formatDateTime(event.end_time)} (
            {formatDuration(event.start_time, event.end_time)})
          </dd>

          <dt>Track IDs</dt>
          <dd>{event.track_ids && event.track_ids.length > 0 ? event.track_ids.join(", ") : "—"}</dd>

          <dt>Trigger confidence</dt>
          <dd>{event.trigger_confidence != null ? `${(event.trigger_confidence * 100).toFixed(0)}%` : "—"}</dd>

          <dt>Event ID</dt>
          <dd className="mono">{event.event_id}</dd>
        </dl>

        {event.worker_summary && (
          <section className="detail-section">
            <h3>Summary</h3>
            <p>{event.worker_summary}</p>
          </section>
        )}

        {event.vlm_summary && event.vlm_summary !== event.worker_summary && (
          <section className="detail-section">
            <h3>VLM description</h3>
            <p>{event.vlm_summary}</p>
          </section>
        )}

        {event.nemotron_reason && (
          <section className="detail-section">
            <h3>Reasoning</h3>
            <p>{event.nemotron_reason}</p>
          </section>
        )}

        {err && <div className="alert alert-error">{err}</div>}

        <div className="drawer-actions">
          <button
            className="btn"
            disabled={updating || event.status === "acknowledged"}
            onClick={() => setStatus("acknowledged")}
          >
            Acknowledge
          </button>
          <button
            className="btn btn-danger"
            disabled={updating || event.status === "dismissed"}
            onClick={() => setStatus("dismissed")}
          >
            Dismiss
          </button>
          {event.status !== "new" && (
            <button className="btn-ghost" disabled={updating} onClick={() => setStatus("new")}>
              Reset to new
            </button>
          )}
        </div>
      </aside>
    </div>
  );
}
