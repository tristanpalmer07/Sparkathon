import { useCallback, useEffect, useMemo, useState } from "react";
import { getStats, listEvents, listVideos } from "../api";
import type { EventItem, StatsResponse, VideoEntry } from "../types";
import { formatDateTime, priorityClass, statusClass } from "../format";
import EventDetailDrawer from "./EventDetailDrawer";

const POLL_MS = 15000;

interface Filters {
  priority: string;
  status: string;
  category: string;
  camera_id: string;
}

const EMPTY_FILTERS: Filters = { priority: "", status: "", category: "", camera_id: "" };

export default function EventsView() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [videos, setVideos] = useState<VideoEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<EventItem | null>(null);

  const load = useCallback(async () => {
    try {
      const [ev, st, vids] = await Promise.all([
        listEvents({
          priority: filters.priority,
          status: filters.status,
          category: filters.category,
          camera_id: filters.camera_id,
          limit: 200,
        }),
        getStats(),
        listVideos().catch(() => [] as VideoEntry[]),
      ]);
      setEvents(ev);
      setStats(st);
      setVideos(vids);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const cameraOptions = useMemo(() => {
    const set = new Set<string>();
    events.forEach((e) => set.add(e.camera_id));
    videos.forEach((v) => v.last_camera_id && set.add(v.last_camera_id));
    return Array.from(set).sort();
  }, [events, videos]);

  const categoryOptions = useMemo(() => {
    const set = new Set<string>();
    events.forEach((e) => e.category && set.add(e.category));
    return Array.from(set).sort();
  }, [events]);

  const totalCount = useMemo(
    () => (stats ? stats.by_priority_status.reduce((sum, r) => sum + r.count, 0) : 0),
    [stats]
  );

  const countFor = (predicate: (row: { priority: string | null; status: string }) => boolean) =>
    stats ? stats.by_priority_status.filter(predicate).reduce((sum, r) => sum + r.count, 0) : 0;

  function updateFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  function handleStatusChanged(updated: EventItem) {
    setEvents((prev) => prev.map((e) => (e.event_id === updated.event_id ? updated : e)));
    setSelected(updated);
    getStats().then(setStats).catch(() => undefined);
  }

  return (
    <div className="events-view">
      <div className="stats-bar">
        <StatTile label="Total events" value={totalCount} />
        <StatTile label="High priority" value={countFor((r) => r.priority === "high")} tone="high" />
        <StatTile label="Medium priority" value={countFor((r) => r.priority === "medium")} tone="medium" />
        <StatTile label="Unreviewed (new)" value={countFor((r) => r.status === "new")} tone="new" />
      </div>

      <div className="filter-bar">
        <select value={filters.priority} onChange={(e) => updateFilter("priority", e.target.value)}>
          <option value="">All priorities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select value={filters.status} onChange={(e) => updateFilter("status", e.target.value)}>
          <option value="">All statuses</option>
          <option value="new">New</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="dismissed">Dismissed</option>
        </select>
        <select value={filters.camera_id} onChange={(e) => updateFilter("camera_id", e.target.value)}>
          <option value="">All cameras</option>
          {cameraOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select value={filters.category} onChange={(e) => updateFilter("category", e.target.value)}>
          <option value="">All categories</option>
          {categoryOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        {(filters.priority || filters.status || filters.category || filters.camera_id) && (
          <button className="btn-ghost" onClick={() => setFilters(EMPTY_FILTERS)}>
            Clear filters
          </button>
        )}
        <button className="btn-ghost" onClick={load} disabled={loading} title="Refresh now">
          ↻ Refresh
        </button>
      </div>

      {error && <div className="alert alert-error">Failed to load events: {error}</div>}

      {loading && events.length === 0 ? (
        <div className="empty-state">Loading events…</div>
      ) : events.length === 0 ? (
        <div className="empty-state">
          No flagged events match these filters yet. Ingest a video from the <strong>Videos</strong> tab to
          generate some.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="events-table">
            <thead>
              <tr>
                <th>Detected</th>
                <th>Camera</th>
                <th>Trigger</th>
                <th>Priority</th>
                <th>Category</th>
                <th>Status</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev) => (
                <tr key={ev.event_id} onClick={() => setSelected(ev)} className="event-row">
                  <td className="col-time">{formatDateTime(ev.created_at)}</td>
                  <td>
                    <code>{ev.camera_id}</code>
                  </td>
                  <td>
                    {ev.trigger_type}
                    {ev.trigger_confidence != null && (
                      <span className="conf"> {(ev.trigger_confidence * 100).toFixed(0)}%</span>
                    )}
                  </td>
                  <td>
                    <span className={priorityClass(ev.priority)}>{ev.priority ?? "—"}</span>
                  </td>
                  <td>{ev.category ?? "—"}</td>
                  <td>
                    <span className={statusClass(ev.status)}>{ev.status}</span>
                  </td>
                  <td className="col-summary">{ev.worker_summary ?? ev.vlm_summary ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <EventDetailDrawer event={selected} onClose={() => setSelected(null)} onStatusChanged={handleStatusChanged} />
      )}
    </div>
  );
}

function StatTile({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className={`stat-tile${tone ? ` stat-${tone}` : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
