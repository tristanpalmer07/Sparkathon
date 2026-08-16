import { useCallback, useEffect, useRef, useState } from "react";
import { listJobs, listVideos, startIngest, uploadVideo } from "../api";
import type { Job, VideoEntry } from "../types";
import { formatBytes } from "../format";
import JobsPanel from "./JobsPanel";

const VIDEOS_POLL_MS = 8000;
const JOBS_POLL_MS = 3000;

export default function VideosView() {
  const [videos, setVideos] = useState<VideoEntry[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cameraIds, setCameraIds] = useState<Record<string, string>>({});
  const [starting, setStarting] = useState<Record<string, boolean>>({});
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadVideos = useCallback(async () => {
    try {
      const vids = await listVideos();
      setVideos(vids);
      setError(null);
      setCameraIds((prev) => {
        const next = { ...prev };
        for (const v of vids) {
          if (!(v.video_id in next)) next[v.video_id] = v.last_camera_id ?? v.suggested_camera_id;
        }
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      setJobs(await listJobs());
    } catch {
      // job polling failures are non-fatal — the videos list still works
    }
  }, []);

  useEffect(() => {
    loadVideos();
    loadJobs();
    const vId = setInterval(loadVideos, VIDEOS_POLL_MS);
    const jId = setInterval(loadJobs, JOBS_POLL_MS);
    return () => {
      clearInterval(vId);
      clearInterval(jId);
    };
  }, [loadVideos, loadJobs]);

  async function handleUpload(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setUploadErr(null);
    setUploadPct(0);
    try {
      await uploadVideo(file, setUploadPct);
      await loadVideos();
    } catch (e) {
      setUploadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setUploadPct(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleIngest(video: VideoEntry) {
    const cameraId = cameraIds[video.video_id]?.trim();
    setStarting((s) => ({ ...s, [video.video_id]: true }));
    try {
      await startIngest(video.source, video.filename, cameraId);
      await loadJobs();
    } catch (e) {
      setUploadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting((s) => ({ ...s, [video.video_id]: false }));
    }
  }

  const library = videos.filter((v) => v.source === "library");
  const uploads = videos.filter((v) => v.source === "upload");

  return (
    <div className="videos-view">
      <section className="upload-section">
        <h2>Upload a video</h2>
        <p className="muted">
          Any common container/codec is accepted — non-H.264 sources are transcoded automatically before being
          fed into the pipeline (VIOS only accepts H.264).
        </p>
        <input
          ref={fileInputRef}
          type="file"
          accept="video/*,.mp4,.mov,.avi,.mkv,.m4v"
          onChange={(e) => handleUpload(e.target.files)}
          disabled={uploadPct !== null}
        />
        {uploadPct !== null && <div className="upload-progress">Uploading… {uploadPct}%</div>}
        {uploadErr && <div className="alert alert-error">{uploadErr}</div>}
      </section>

      {error && <div className="alert alert-error">Failed to load videos: {error}</div>}

      {loading ? (
        <div className="empty-state">Loading videos…</div>
      ) : (
        <>
          <VideoTable
            title="Demo library"
            subtitle="ChimpACT dataset footage bundled for this demo"
            videos={library}
            cameraIds={cameraIds}
            setCameraId={(id, val) => setCameraIds((c) => ({ ...c, [id]: val }))}
            starting={starting}
            onIngest={handleIngest}
          />
          <VideoTable
            title="Uploaded videos"
            subtitle="Files uploaded through this page"
            videos={uploads}
            cameraIds={cameraIds}
            setCameraId={(id, val) => setCameraIds((c) => ({ ...c, [id]: val }))}
            starting={starting}
            onIngest={handleIngest}
            emptyText="No uploads yet — use the form above."
          />
        </>
      )}

      <JobsPanel jobs={jobs} />
    </div>
  );
}

function VideoTable({
  title,
  subtitle,
  videos,
  cameraIds,
  setCameraId,
  starting,
  onIngest,
  emptyText,
}: {
  title: string;
  subtitle: string;
  videos: VideoEntry[];
  cameraIds: Record<string, string>;
  setCameraId: (videoId: string, val: string) => void;
  starting: Record<string, boolean>;
  onIngest: (v: VideoEntry) => void;
  emptyText?: string;
}) {
  return (
    <section className="video-section">
      <h2>{title}</h2>
      <p className="muted">{subtitle}</p>
      {videos.length === 0 ? (
        <div className="empty-state">{emptyText ?? "No videos found."}</div>
      ) : (
        <div className="table-wrap">
          <table className="events-table">
            <thead>
              <tr>
                <th>Filename</th>
                <th>Size</th>
                <th>Camera ID</th>
                <th>Last run</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {videos.map((v) => (
                <tr key={v.video_id}>
                  <td className="mono">{v.filename}</td>
                  <td>{formatBytes(v.size_bytes)}</td>
                  <td>
                    <input
                      className="camera-id-input"
                      value={cameraIds[v.video_id] ?? v.suggested_camera_id}
                      onChange={(e) => setCameraId(v.video_id, e.target.value)}
                      placeholder={v.suggested_camera_id}
                    />
                  </td>
                  <td>
                    {v.last_status ? (
                      <span className={`badge badge-${jobBadgeTone(v.last_status)}`}>{v.last_status}</span>
                    ) : (
                      <span className="muted">never run</span>
                    )}
                  </td>
                  <td>
                    <button className="btn" disabled={!!starting[v.video_id]} onClick={() => onIngest(v)}>
                      {starting[v.video_id] ? "Starting…" : "Ingest"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function jobBadgeTone(status: string): string {
  switch (status) {
    case "succeeded":
      return "status-ack";
    case "failed":
      return "high";
    case "queued":
      return "neutral";
    default:
      return "medium";
  }
}
